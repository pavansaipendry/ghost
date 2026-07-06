"""Screen Vision for Ghost AI — on-device "sees your screen" context source.

This is the HuddleMate-parity capability: Ghost doesn't just *hear* the interview,
it *reads* what's on screen — the coding problem in CoderPad/HackerRank, the slide
being shared in Zoom, the doc in a browser tab — and feeds that text as live context
into the Claude prompt.

Everything is on-device:
    - Capture:  Quartz.CGWindowListCreateImage on the target app's window
                (capturing a specific window excludes Ghost's own overlay, and
                 reuses the Screen Recording permission Ghost already requires).
    - OCR:      macOS Vision framework (VNRecognizeTextRequest), accurate level.
                No network, no API cost, nothing to detect.

Usage (standalone):
    sv = ScreenVision()
    text = sv.read(pid=12345)          # one-shot read of an app's window
    print(text)

Usage (continuous, feeding the brain):
    sv = ScreenVision()
    sv.start(pid=12345, on_text=lambda t: context_loader.set_screen_context(t))
    # ... interview happens; on_text fires only when the screen text changes ...
    sv.stop()
"""

import difflib
import os
import subprocess
import tempfile
import threading
import time

import Quartz
import Vision
from Foundation import NSURL

# macOS screenshot CLI. Used instead of CGDisplayCreateImage/CGWindowListCreateImage,
# which Apple deprecated — on macOS 14+/26 they return nil even WITH Screen Recording
# permission. `screencapture` still works and respects the same permission.
_SCREENCAPTURE = "/usr/sbin/screencapture"


# Cap how much screen text we inject into the prompt — protects latency/context budget.
MAX_SCREEN_CHARS = 4000

# Vision recognition level: 1 = accurate, 0 = fast. Accurate is fine at our cadence.
_RECOGNITION_LEVEL_ACCURATE = getattr(
    Vision, "VNRequestTextRecognitionLevelAccurate", 1
)


def find_window_for_pid(pid: int):
    """Return the CGWindowID of the largest on-screen normal window owned by `pid`.

    Meeting apps and browsers spawn many windows/helpers; we want the biggest
    normal (layer 0) window — that's the one showing the content. Returns None
    if the app has no visible window.
    """
    options = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements
    )
    window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    if not window_list:
        return None

    best_id = None
    best_area = 0
    for w in window_list:
        if pid is not None and w.get("kCGWindowOwnerPID") != pid:
            continue
        # Normal app windows live on layer 0; skip menus, shadows, status items.
        if w.get("kCGWindowLayer", 0) != 0:
            continue
        bounds = w.get("kCGWindowBounds", {})
        area = bounds.get("Width", 0) * bounds.get("Height", 0)
        if area < 200 * 200:  # ignore tiny/empty windows
            continue
        if area > best_area:
            best_area = area
            best_id = w.get("kCGWindowNumber")
    return best_id


def _capture_png(window_id: int = None) -> str:
    """Capture the screen (or a specific window) to a temp PNG via `screencapture`.

    Returns the file path, or None on failure. `-x` = silent, `-o` = no window shadow.
    """
    path = os.path.join(tempfile.gettempdir(), f"ghost_screen_{os.getpid()}.png")
    cmd = [_SCREENCAPTURE, "-x", "-o"]
    if window_id is not None:
        cmd += ["-l", str(window_id)]
    cmd += [path]
    try:
        subprocess.run(cmd, capture_output=True, timeout=8)
    except Exception as e:
        print(f"[ScreenVision] screencapture failed: {e}")
        return None
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    return None


def capture_screen_base64(window_id: int = None):
    """Capture the screen to PNG and return (base64_str, media_type), or None.

    Whole-screen capture (window_id=None) is the reliable path for a screen-shared
    question: a video-call share renders into the call window as ordinary pixels, which
    a full-display screenshot picks up even when window-targeted capture or OCR misses
    the GPU-composited video. The PNG is sent straight to the vision model — no OCR.
    """
    import base64

    path = _capture_png(window_id)
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            return None
        return base64.standard_b64encode(data).decode("ascii"), "image/png"
    except OSError as e:
        print(f"[ScreenVision] read screenshot failed: {e}")
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def ocr_image_file(path: str) -> str:
    """Run on-device OCR (macOS Vision) on an image file. Returns recognized text."""
    if not path or not os.path.exists(path):
        return ""
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(path), None
    )
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(_RECOGNITION_LEVEL_ACCURATE)
    request.setUsesLanguageCorrection_(True)

    ok, _err = handler.performRequests_error_([request], None)
    if not ok:
        return ""

    lines = []
    for obs in (request.results() or []):
        candidates = obs.topCandidates_(1)
        if candidates and len(candidates):
            lines.append(str(candidates[0].string()))
    return "\n".join(lines)


class ScreenVision:
    """Captures and OCRs an app window on-device, on demand or continuously."""

    def __init__(self, max_chars: int = MAX_SCREEN_CHARS):
        self._max_chars = max_chars
        self._running = False
        self._thread = None
        self._last_text = ""

    def read(self, pid: int = None) -> str:
        """One-shot: capture the target app's window (or whole screen) and OCR it.

        Args:
            pid: PID of the app whose window to read. If None, reads the main display.

        Returns:
            Recognized text, trimmed to max_chars. Empty string on failure.
        """
        window_id = find_window_for_pid(pid) if pid is not None else None
        path = _capture_png(window_id)
        if not path:
            return ""
        try:
            text = ocr_image_file(path).strip()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if len(text) > self._max_chars:
            text = text[: self._max_chars] + "\n…(truncated)"
        return text

    def start(self, pid: int = None, on_text=None, interval: float = 2.0,
              min_change: float = 0.10):
        """Continuously read the screen and fire on_text ONLY when it changes.

        Firing only on meaningful change keeps the prompt stable and cheap — we
        don't re-inject identical screen text every couple seconds.

        Args:
            pid: PID of the app to watch (None = whole main display).
            on_text: Callback(text) — called when screen text changes enough.
            interval: Seconds between captures.
            min_change: Minimum difference ratio (0-1) vs. last text to count as
                        a change. 0.10 ≈ "at least ~10% different".
        """
        if self._running:
            return
        self._running = True
        self._last_text = ""

        def _loop():
            while self._running:
                try:
                    text = self.read(pid=pid)
                    if text and self._changed_enough(text, min_change):
                        self._last_text = text
                        if on_text:
                            on_text(text)
                except Exception as e:
                    print(f"[ScreenVision] read error: {e}")
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        print(f"[ScreenVision] Watching pid={pid} every {interval}s (on-device OCR)")

    def stop(self):
        """Stop continuous watching."""
        self._running = False
        print("[ScreenVision] Stopped")

    def _changed_enough(self, text: str, min_change: float) -> bool:
        """True if `text` differs from the last emitted text by >= min_change."""
        if not self._last_text:
            return True
        ratio = difflib.SequenceMatcher(None, self._last_text, text).ratio()
        return (1.0 - ratio) >= min_change
