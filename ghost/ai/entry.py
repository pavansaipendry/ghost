#!/usr/bin/env python3
"""Ghost AI - Stealth Interview Assistant with real-time audio -> answer pipeline.

Run as:
    python -m ghost.ai.entry --app "zoom.us" --context ./my_context/
    python -m ghost.ai.entry --app "Google Chrome" --api-key sk-ant-...

Keyboard shortcuts:
    Ctrl+1-7   Switch to document view
    Ctrl+0     Switch to AI view
    Ctrl+8     Switch to Live chat (if --room provided)
    Ctrl+9     Kill switch - stop all AI processing instantly
    Ctrl+Shift+Q  Quit Ghost
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import platform

import AppKit
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSOperationQueue
from Foundation import NSURL

from ghost.config import get_config, save_state
from ghost.window.panel import GhostPanel
from ghost.window.webview import GhostWebView
from ghost.input.keys import GhostKeyListener
from ghost.ui.tray import GhostTray
from ghost.documents.loader import load_document, get_extension, is_supported

from ghost.ai.claude_brain import ClaudeBrain, ContextLoader, detect_answer_mode
from ghost.ai.pipeline import GhostAIPipeline
from ghost.ai.session_logger import SessionLogger
from ghost.ai.screen_vision import ScreenVision, capture_screen_base64
from ghost.ai.audio_capture import find_pid_by_app
from ghost.ai.hud import GhostHUD


def _load_dotenv():
    """Load KEY=VALUE pairs from a .env file at the project root into os.environ.

    Lets the user paste ANTHROPIC_API_KEY into .env once instead of exporting it
    every session. Existing env vars win (setdefault), so an exported key still works.
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, val)
        print(f"[GhostAI] Loaded environment from {env_path}")
    except Exception as e:
        print(f"[GhostAI] Could not read .env: {e}")


# Virtual keycodes
_VK_0 = 29   # Key "0"
_VK_8 = 28   # Key "8"
_VK_9 = 25   # Key "9"


class AIKeyListener(GhostKeyListener):
    """Extends GhostKeyListener with Ctrl+0 (AI view), Ctrl+9 (kill switch)."""

    def __init__(self, on_document_switch, on_back, on_quit, on_ctrl_toggle=None,
                 on_ai_view=None, on_kill=None, on_answer_now=None,
                 on_vision=None, on_hud_toggle=None, on_ask=None):
        super().__init__(on_document_switch, on_back, on_quit, on_ctrl_toggle)
        self._on_ai_view = on_ai_view
        self._on_kill = on_kill
        self._on_answer_now = on_answer_now
        self._on_vision = on_vision           # double-tap Right-Shift
        self._on_hud_toggle = on_hud_toggle   # double-tap Right-Command
        self._on_ask = on_ask                 # Ctrl+A -> focus the Ask input
        self._alt_pressed = False
        self._last_ralt_time = 0.0   # for double-tap Right Option detection
        self._last_rshift_time = 0.0  # for double-tap Right Shift (vision)
        self._last_rcmd_time = 0.0    # for double-tap Right Command (HUD toggle)

    def _on_press(self, key):
        from pynput import keyboard

        # Track modifiers
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
            self._ctrl_pressed = True
            if self._on_ctrl_toggle:
                self._on_ctrl_toggle(True)
            return
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
            self._shift_pressed = True
            # Double-tap RIGHT Shift = "answer what's on screen NOW" (vision).
            # Modifier-only -> nothing typed into the focused app (no stealth leak).
            if key == keyboard.Key.shift_r:
                now = time.time()
                if 0 < (now - self._last_rshift_time) < 0.4:
                    self._last_rshift_time = 0.0
                    if self._on_vision:
                        self._on_vision()
                else:
                    self._last_rshift_time = now
            return
        if key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r, keyboard.Key.cmd):
            # Double-tap RIGHT Command = show/hide the floating HUD box (and focus it).
            if key == keyboard.Key.cmd_r:
                now = time.time()
                if 0 < (now - self._last_rcmd_time) < 0.4:
                    self._last_rcmd_time = 0.0
                    if self._on_hud_toggle:
                        self._on_hud_toggle()
                else:
                    self._last_rcmd_time = now
            return
        if key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt):
            self._alt_pressed = True
            # Double-tap RIGHT Option = "question is done, answer NOW".
            # Modifier-only, so NOTHING is typed into the focused app (no leak).
            if key == keyboard.Key.alt_r:
                now = time.time()
                if 0 < (now - self._last_ralt_time) < 0.4:
                    self._last_ralt_time = 0.0  # consume, avoid triple-tap re-fire
                    if self._on_answer_now:
                        self._on_answer_now()
                else:
                    self._last_ralt_time = now
            return

    def _on_release(self, key):
        from pynput import keyboard
        if key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt):
            self._alt_pressed = False
        super()._on_release(key)

        # Ctrl+Esc -> back
        if self._ctrl_pressed and key == keyboard.Key.esc:
            self._on_back()
            return

        # Ctrl+Shift+Q -> quit
        if self._ctrl_pressed and self._shift_pressed:
            if hasattr(key, "char") and key.char in ("q", "Q"):
                self._on_quit()
                return
            if hasattr(key, "vk") and key.vk == 12:
                self._on_quit()
                return

        # Ctrl+A -> focus the "Ask the LLM" input (type a question without clicking).
        # Ctrl+A yields the control char '\x01' on macOS; accept the letter + vk 0 too.
        if self._ctrl_pressed:
            is_a = (getattr(key, "char", None) in ("\x01", "a", "A")
                    or (getattr(key, "vk", None) == 0))
            if is_a:
                if self._on_ask:
                    self._on_ask()
                return

        # Ctrl + number keys
        if self._ctrl_pressed and hasattr(key, "vk") and key.vk is not None:
            from ghost.input.keys import _VK_MAP
            number = _VK_MAP.get(key.vk)
            if number is not None:
                if 1 <= number <= 7:
                    self._on_document_switch(number)
                    return
                if number == 0:
                    # Ctrl+0 -> AI view
                    if self._on_ai_view:
                        self._on_ai_view()
                    return

            # Ctrl+9 -> kill switch
            if key.vk == _VK_9:
                if self._on_kill:
                    self._on_kill()
                return

        # Fallback char-based
        if self._ctrl_pressed and hasattr(key, "char") and key.char is not None:
            if key.char in "1234567":
                self._on_document_switch(int(key.char))
                return
            if key.char == "0":
                if self._on_ai_view:
                    self._on_ai_view()
                return
            if key.char == "9":
                if self._on_kill:
                    self._on_kill()
                return


class GhostAIApp:
    """Ghost with AI superpowers - audio -> Whisper -> Claude -> stealth display."""

    MAX_DOCUMENTS = 7

    def __init__(self):
        self._documents = {}
        self._next_slot = 1
        self._panel = None
        self._webview = None
        self._keys = None
        self._tray = None
        self._pipeline = None
        self._brain = None
        self._logger = None
        self._context_loader = None
        self._screen_vision = None
        self._screen_box = None           # floating stealth box: "SCREEN - what Ghost sees"
        self._prev_output_device = None   # restore audio output on quit (BlackHole mode)
        # AudioObjectIDs are NOT stable across device replug/reconnect (AirPods
        # dropping and coming back gets them a NEW id). Restoring by a launch-time
        # id can therefore point at nothing, or at the wrong device - the UID is
        # the stable identity, so that's what quit-restore resolves against.
        self._prev_output_uid = None
        # No-audio / routing watchdog state. Keyed on the INTERVIEWER source
        # specifically (see _check_routing_loss) - the old version keyed on the
        # OVERALL peak, which is the max of both sources, so in dual-voice mode
        # YOUR OWN mic energy marked "audio seen" and masked a dead interviewer
        # feed completely. That left one clean path to the silent
        # nothing-recorded failure: a call app whose speaker is pinned to a real
        # device (not 'Same as System') bypasses Ghost, passes the pre-flight
        # (which only proves SYSTEM audio routes), and no watchdog ever fired.
        self._silence_warned = False      # one-shot "never captured" warning fired
        self._NO_AUDIO_WARN_SECONDS = 15.0
        self._session_start = None        # when the pipeline actually started listening
        # Continuous cross-source routing-loss watchdog (dual-voice mode). The
        # one-shot no-audio check above only fires if audio NEVER arrives; it can't
        # catch capture dying MID-session (the "worked, then only my voice" failure).
        # This does: if the interviewer feed (BlackHole) goes dead for a long stretch
        # WHILE the mic is clearly active (a conversation is happening), the call
        # audio has stopped reaching Ghost - warn loudly and keep checking.
        self._iv_ever = False             # interviewer audio seen at least once
        self._iv_last_energy = 0.0        # last time interviewer had real energy
        self._you_last_energy = 0.0       # last time your mic had speech energy
        self._routing_lost = False        # cross-source loss currently flagged
        self._ROUTING_LOSS_SECONDS = 25.0 # interviewer-silent window that trips it
        # Routing banner: a blocking red banner shown in the AI view when the
        # interviewer's audio isn't reaching Ghost (preflight fail or the output
        # device got switched away mid-session). Stored so it replays on view load.
        self._pending_banner = None       # (message, kind) or None
        self._banner_lock = threading.Lock()
        self._output_watch_running = False
        self._blackhole_mode = False      # are we capturing via BlackHole this session
        # Full chat history (Python-side source of truth) - survives view switches
        # and is saved to disk so chats are never lost.
        self._chat_history = []
        self._chat_lock = threading.Lock()
        # Predictive prefetch: speculatively answer a high-confidence partial, then
        # adopt it on commit if it matches. Epoch guards against stale token streams.
        self._answer_epoch = 0
        self._answer_lock = threading.Lock()
        self._prefetch_text = None
        self._prefetch_in_flight = False
        self._current_view = "documents"  # "documents" or "ai"
        self._ai_web_dir = os.path.join(os.path.dirname(__file__), "web")
        self._ai_web_dir = os.path.abspath(self._ai_web_dir)

    def run(self):
        # Load .env (so ANTHROPIC_API_KEY can live in a file, not the shell)
        _load_dotenv()

        # Parse args
        parser = argparse.ArgumentParser(description="Ghost AI - Stealth Interview Assistant")
        parser.add_argument("--app", default=None, help="Target app to capture audio from (e.g., 'zoom.us', 'Google Chrome')")
        parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
        parser.add_argument("--context", default=None, help="Directory with context files (resume.md, projects.md, etc.)")
        parser.add_argument("--model", default="claude-opus-4-8", help="Claude model to use")
        parser.add_argument("--whisper", default="small", help="Whisper model size (tiny, small, medium, large, turbo)")
        parser.add_argument("--voice-profile", default=None, help="Path to saved voice profile (.npz)")
        parser.add_argument("--mic", action="store_true", help="Use microphone instead of ScreenCaptureKit (for apps like Zoom whose VoIP audio bypasses SCK)")
        parser.add_argument("--blackhole", action="store_true", help="Use BlackHole virtual audio device for lossless capture (requires: brew install blackhole-2ch)")
        parser.add_argument("--interviewer-only", action="store_true", help="SPEAKERS mode: ignore the mic entirely so the interviewer is NEVER mislabeled as you (you lose your own-voice capture, but no mixing). Use this if you're not on headphones.")
        parser.add_argument("--parakeet", action="store_true", help="Use on-device Parakeet (NVIDIA TDT via mlx) for the interviewer transcript instead of Apple SFSpeech. Fixes the ~20-30min recognizer death + vanishing partials and improves tech-term accuracy. Still 100%% local.")
        parser.add_argument("--no-screen", action="store_true", help="Disable on-device screen-vision (Ghost reads the shared screen/coding pad via OCR by default)")
        parser.add_argument("--screen-app", default=None, help="App window to read on-screen (defaults to --app; e.g. read 'Google Chrome' coding pad while listening to 'zoom.us')")
        parser.add_argument("files", nargs="*", help="Document files to load (optional)")
        args = parser.parse_args()

        # macOS version check
        mac_ver = platform.mac_ver()[0]
        if mac_ver:
            major = int(mac_ver.split(".")[0])
            if major < 12:
                print(f"WARNING: macOS {mac_ver} detected. Stealth mode requires macOS 12+.")

        # Set up as accessory app
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        # Create UI components
        self._webview = GhostWebView(on_message=self._on_webview_message)
        self._panel = GhostPanel()
        self._panel.set_webview(self._webview.get_native_view())
        self._webview.set_on_files_dropped(self._load_files)

        self._tray = GhostTray.alloc().init()
        self._tray._on_load_documents = self._load_files
        self._tray._on_quit = self._quit
        self._tray._on_opacity_change = self._set_opacity
        self._tray._on_show_window = self._show_window
        self._tray.setup()

        # Key listener with AI shortcuts
        self._keys = AIKeyListener(
            on_document_switch=self._switch_document_threadsafe,
            on_back=self._go_back_threadsafe,
            on_quit=self._quit_threadsafe,
            on_ctrl_toggle=self._ctrl_toggle_threadsafe,
            on_ai_view=self._show_ai_view_threadsafe,
            on_kill=self._kill_switch_threadsafe,
            on_answer_now=self._answer_now,
            on_vision=self._on_vision,
            on_hud_toggle=self._on_hud_toggle,
            on_ask=self._focus_ask_threadsafe,
        )
        self._keys.start()

        # Load document files
        if args.files:
            paths = [p for p in args.files if os.path.isfile(p) and is_supported(p)]
            if paths:
                self._load_files(paths)

        # Auto-load from sample_docs
        if not self._documents:
            self._auto_load_documents()

        # Set up Claude Brain
        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            context_loader = ContextLoader(context_dir=args.context) if args.context else ContextLoader()
            self._context_loader = context_loader
            self._brain = ClaudeBrain(api_key=api_key, context_loader=context_loader, model=args.model)
            print("[GhostAI] Claude Brain initialized")
        else:
            print("[GhostAI] WARNING: No API key set. AI answers disabled.")
            print("[GhostAI] Set ANTHROPIC_API_KEY env var or pass --api-key")

        # Set up session logger
        self._logger = SessionLogger()

        # Set up BlackHole if requested (auto-creates 'Ghost Audio' + switches output)
        if args.blackhole:
            try:
                from ghost.ai.blackhole_setup import setup_blackhole, verify_blackhole_routing
                _, self._prev_output_device = setup_blackhole()

                # Resolve the RESTORE identity as a UID right now, while the device
                # still exists. Raw AudioObjectIDs go stale the moment the device
                # replugs (see _restore_output).
                try:
                    from ghost.ai.blackhole_setup import _get_device_uid
                    if self._prev_output_device:
                        self._prev_output_uid = _get_device_uid(self._prev_output_device)
                except Exception:
                    self._prev_output_uid = None

                # PRE-FLIGHT: confirm system audio actually reaches BlackHole. If it
                # doesn't, the interviewer's voice won't be captured and the session
                # would silently record nothing - the exact "doesn't work at all" bug.
                # Catch it HERE, loudly, so it can be fixed before the interview.
                # (This is the ONLY place the audible test tone is allowed: we're
                # pre-interview by definition. Never run it mid-session.)
                print("[GhostAI] Testing audio routing (you'll hear a short blip)...")
                ok, rms = verify_blackhole_routing()
                self._blackhole_mode = True
                if ok:
                    print(f"[GhostAI] ✅ Audio routing OK - BlackHole is receiving system audio (rms={rms:.3f}).")
                    print("[GhostAI]    The interviewer's voice WILL be captured.")
                else:
                    print("[GhostAI] ⛔ AUDIO ROUTING BROKEN - BlackHole is NOT receiving system audio!")
                    print("[GhostAI]    The interviewer's voice will NOT be captured. Fix before your call:")
                    print("[GhostAI]    1. System Settings → Sound → Output → select 'Ghost Audio'.")
                    print("[GhostAI]    2. In your CALL APP (Zoom/Meet/Teams) audio settings, set the")
                    print("[GhostAI]       SPEAKER/Output to 'Ghost Audio' (or 'Same as System').")
                    print("[GhostAI]    3. Make sure the call is playing audio, then relaunch.")
                    # BLOCKING in-app banner - don't let a dead session start silently.
                    self._set_routing_banner(
                        "Audio routing is broken - the interviewer is NOT being captured. "
                        "Fix: System Settings → Sound → Output → 'Ghost Audio', and set your "
                        "call app's speaker to 'Ghost Audio' (or 'Same as System'). "
                        "Ghost keeps checking and will clear this once audio flows.",
                        "error",
                    )
            except Exception as e:
                print(f"[GhostAI] BlackHole setup failed: {e}")
                print("[GhostAI] Falling back to --mic mode")
                args.blackhole = False
                args.mic = True

        # Set up audio pipeline
        if args.blackhole or args.mic or args.app:
            self._setup_pipeline(
                args.app, args.whisper, args.voice_profile,
                use_mic=args.mic, use_blackhole=args.blackhole,
                # Both voices by default (best on headphones). On speakers, --interviewer-only
                # disables the mic so the interviewer is never mislabeled as you.
                track_user_voice=not args.interviewer_only,
                use_parakeet=args.parakeet,
            )

        # Set up screen-vision - Ghost reads the shared screen / coding pad (OCR,
        # on-device) and feeds it as live context. Needs the brain (to inject) and
        # Screen Recording permission (already required for audio).
        if self._context_loader and not args.no_screen:
            self._setup_screen_vision(args.screen_app or args.app)

        # Show window - default to the AI chat view when we're actively listening,
        # so the conversation log builds from the start (switching to docs resets it).
        if self._pipeline:
            self._show_ai_view()
        self._panel.show()

        # BlackHole mid-session watchdog: if the default output stops being 'Ghost
        # Audio' (e.g. AirPods reconnect), interviewer capture goes dead - detect it
        # and try to re-route, surfacing a banner either way.
        if self._blackhole_mode and self._pipeline:
            self._start_output_watchdog()

        print("\nGhost AI is running.")
        print("  Ctrl+1-7   Document view")
        print("  Ctrl+0     AI view")
        print("  Ask the LLM   Type in the box at the bottom of the AI view (hold Ctrl to click)")
        print("  Double-tap Right-Option   Answer NOW (interviewer's spoken question)")
        print("  Double-tap Right-Shift    Answer what's ON SCREEN (vision/screenshot)")
        print("  Ctrl+9     Kill switch")
        print("  Ctrl+Shift+Q  Quit")
        if args.blackhole:
            print(f"  Listening via: BLACKHOLE (lossless, 10/10)")
        elif args.mic:
            print(f"  Listening via: MICROPHONE (speaker audio)")
        elif args.app:
            print(f"  Listening to: {args.app}")
        print()

        app.run()

    def _setup_pipeline(self, target_app, whisper_model, voice_profile, use_mic=False,
                        use_blackhole=False, track_user_voice=False, use_parakeet=False):
        """Initialize the AI audio pipeline."""
        # Bias the on-device recognizer toward my resume/JD vocabulary (project names,
        # tech jargon, acronyms) so the interviewer transcript stops mangling them.
        contextual_strings = (
            self._context_loader.build_contextual_strings() if self._context_loader else []
        )
        if contextual_strings:
            print(f"[GhostAI] STT primed with {len(contextual_strings)} context terms")
        try:
            self._pipeline = GhostAIPipeline(
                target_app=target_app,
                whisper_model=whisper_model,
                contextual_strings=contextual_strings,
                on_question=self._on_question_detected,
                on_prefetch=self._on_prefetch,
                on_status=self._on_pipeline_status,
                on_audio_chunk=self._on_audio_chunk_for_logger,
                on_user_response=self._on_user_response,
                on_safety_trigger=self._on_safety_trigger,
                on_audio_level=self._on_audio_level,
                on_source_level=self._on_source_level,
                on_live_transcript=self._on_live_transcript,
                on_final_transcript=self._on_final_transcript,
                voice_profile_path=voice_profile,
                use_mic=use_mic,
                use_blackhole=use_blackhole,
                track_user_voice=track_user_voice,
                use_parakeet=use_parakeet,
            )
            self._pipeline.start()
            self._session_start = time.time()
            source = "BLACKHOLE" if use_blackhole else ("MICROPHONE" if use_mic else target_app)
            print(f"[GhostAI] Audio pipeline started for: {source}")
        except Exception as e:
            print(f"[GhostAI] Failed to start audio pipeline: {e}")
            print("[GhostAI] AI view will work but without auto-detection.")
            # A pipeline that failed to start must not look "listening" to the rest
            # of the app (view status, watchdogs, answer_now would all act on a
            # half-constructed object).
            self._pipeline = None

    def _setup_screen_vision(self, screen_app):
        """Start on-device screen-vision feeding live OCR'd screen text into context."""
        try:
            screen_pid = find_pid_by_app(screen_app) if screen_app else None
            if screen_app and screen_pid is None:
                print(f"[GhostAI] Screen-vision: app '{screen_app}' not found, reading whole screen")
            self._screen_vision = ScreenVision()
            self._screen_vision.start(
                pid=screen_pid,
                on_text=self._on_screen_text,
                interval=2.0,
            )
            target = screen_app if screen_pid else "whole screen"
            print(f"[GhostAI] Screen-vision started (reading: {target})")
            # SCREEN display box removed - the OCR still feeds Claude as silent context
            # (see _on_screen_text); we just don't show a floating "what Ghost sees" box.
            # self._screen_box stays None, so all its guards below safely no-op.
        except Exception as e:
            print(f"[GhostAI] Screen-vision failed to start (non-critical): {e}")

    def _on_screen_text(self, text):
        """Screen OCR changed -> feed Claude as context AND show it in the SCREEN box."""
        # Feed the full text to Claude as silent context.
        if self._context_loader:
            self._context_loader.set_screen_context(text)
        print(f"[GhostAI] Screen OCR: {len(text)} chars")
        # Show it in the separate floating SCREEN box (set_screen marshals to main thread).
        if self._screen_box:
            self._screen_box.set_screen(text)

    # ── AI Callbacks (called from background threads) ──

    @staticmethod
    def _norm_words(s):
        return set(re.sub(r'[^a-z0-9 ]', '', (s or "").lower()).split())

    def _should_adopt_prefetch(self, committed_text):
        """True if the in-flight prefetch answers essentially the committed question.

        Requires high word overlap AND that the committed question didn't add much
        beyond the prefetched text - otherwise the prefetch was premature (answered
        an incomplete question) and we must answer fresh.
        """
        if not self._prefetch_in_flight or not self._prefetch_text:
            return False
        wp = self._norm_words(self._prefetch_text)
        wc = self._norm_words(committed_text)
        if not wp or not wc:
            return False
        jaccard = len(wp & wc) / len(wp | wc)
        added = len(wc - wp)
        return jaccard >= 0.6 and added <= 3

    def _begin_answer(self, text, is_follow_up, confidence, is_prefetch=False):
        """Start streaming a Claude answer for `text` into the AI view.

        Epoch-guarded: if a newer answer starts, this one's tokens/finalize are
        dropped - prevents a superseded (e.g. wrong-guess prefetch) stream from
        interleaving with the real answer.
        """
        if not self._brain:
            return

        with self._answer_lock:
            self._answer_epoch += 1
            epoch = self._answer_epoch

        # ACTUALLY STOP the superseded stream, don't just hide it. The epoch guard
        # only drops the old stream's tokens from the UI; the request itself keeps
        # running - streaming, billing, and eating rate limit. Prefetch makes this
        # concrete: as a long question builds, prefetch can restart several times,
        # and without this cancel each restart stacked ANOTHER live Claude stream.
        # cancel_hud too: a typed/vision answer runs on the brain's separate HUD
        # flag, so cancel() alone left it streaming invisibly behind the epoch guard.
        self._brain.cancel()
        self._brain.cancel_hud()

        # Feed the FULL conversation (incl. Ghost's own prior answers) as memory.
        self._sync_memory()

        mode = detect_answer_mode(text, is_follow_up)
        if self._logger and not is_prefetch:
            self._logger.log_question(text, confidence, is_follow_up, mode)

        def _start():
            self._eval_ai_js("GhostAI.aiStart()")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_start)

        print(f"[GhostAI] {'Prefetch' if is_prefetch else 'Answering'} (mode={mode}): {text[:60]}")
        _answer_start = time.time()

        def on_token(token):
            if epoch != self._answer_epoch:
                return  # superseded - drop stale tokens
            def _do():
                self._eval_ai_js(f"GhostAI.aiToken({json.dumps(token)})")
            NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

        def on_done(full_text, answer_mode):
            if epoch != self._answer_epoch:
                return  # superseded - don't finalize
            latency = time.time() - _answer_start
            print(f"[GhostAI] Answer complete ({len(full_text)} chars, {latency:.1f}s)")
            if self._logger:
                self._logger.log_answer(text, full_text, mode, latency)
            self._record_chat("ai", full_text)
            def _do():
                self._eval_ai_js("GhostAI.aiDone()")
            NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
            if self._pipeline:
                self._pipeline.notify_answer_done()
            # anticipate_followup deliberately NOT called: _show_followup is a no-op
            # (follow-up predictions aren't shown in the chat UI), so the call was a
            # pure per-answer API cost - and with FAST_MODEL misconfigured to Opus,
            # an expensive one. Re-add it here if the UI ever consumes predictions.

        def on_error(err):
            if epoch != self._answer_epoch:
                return
            # A dead prefetch must not stay adoptable: if this speculative stream
            # errored and the question then commits with matching text, adoption
            # would point at a stream that produced nothing - the interviewer's
            # question would silently get NO answer. Clearing the flag makes the
            # commit take the fresh-answer path instead.
            self._prefetch_in_flight = False
            print(f"[GhostAI] Claude error: {err}")
            if self._logger:
                self._logger.log_error(err, "claude_api")
            def _do():
                self._eval_ai_js(f"GhostAI.showError({json.dumps(err)})")
            NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

        self._brain.answer_question(
            question=text, is_follow_up=is_follow_up,
            on_token=on_token, on_done=on_done, on_error=on_error,
        )

    def _on_prefetch(self, text, confidence):
        """High-confidence partial - speculatively start answering BEFORE commit.

        So tokens are often already streaming by the time the question is committed
        (double-tap Right-Option or silence). Sonnet quality, earlier start.
        """
        if not self._brain:
            return
        if self._prefetch_in_flight and self._should_adopt_prefetch(text):
            return  # already speculatively answering this - don't restart
        self._prefetch_text = text
        self._prefetch_in_flight = True
        if self._current_view != "ai":
            self._show_ai_view_threadsafe()
        self._begin_answer(text, is_follow_up=False, confidence=confidence, is_prefetch=True)

    def _on_question_detected(self, text, confidence, is_follow_up):
        """Question committed -> adopt the prefetch if it matches, else answer fresh."""
        print(f"[GhostAI] Question detected ({confidence}%): {text}")
        if not self._brain:
            return

        # Adopt: the speculative answer already covers this question - keep streaming it.
        if self._should_adopt_prefetch(text):
            self._prefetch_in_flight = False
            if self._logger:
                mode = detect_answer_mode(text, is_follow_up)
                self._logger.log_question(text, confidence, is_follow_up, mode)
            print(f"[GhostAI] Adopted prefetch for: {text[:60]}")
            return

        # No usable prefetch - answer fresh. (_begin_answer cancels any speculative
        # stream itself, right after bumping the epoch.)
        self._prefetch_in_flight = False
        self._begin_answer(text, is_follow_up, confidence, is_prefetch=False)

    def _record_chat(self, speaker, text):
        """Record a message in the persistent history (saved to disk).

        Merges consecutive same-speaker utterances into one turn - matching the
        chat UI - so a pausing speaker stays one entry, not many fragments.
        """
        text = (text or "").strip()
        if not text:
            return
        with self._chat_lock:
            if self._chat_history and self._chat_history[-1]["speaker"] == speaker:
                self._chat_history[-1]["text"] = (
                    self._chat_history[-1]["text"] + " " + text
                ).strip()
            else:
                self._chat_history.append({"speaker": speaker, "text": text})
            snapshot = list(self._chat_history)
        if self._logger:
            self._logger.save_chat(snapshot)

    # ── Conversation memory (full chat -> Claude context) ──

    _MEMORY_MAX_TURNS = 60   # cap injected history so the prompt stays bounded

    def _conversation_memory(self) -> str:
        """Format the FULL labeled chat log into a transcript for Claude's context,
        so every answer (spoken, typed, vision) sees the whole conversation and never
        contradicts itself.

        Three distinct labels so Claude knows WHO actually said WHAT:
          - 'Interviewer:'          - the other person (their real, merged question).
          - 'Me:'                   - what I actually said out loud (mic ground truth).
          - 'Me (draft I prepared):'- an answer Ghost previously drafted for me, which
                                       I may or may not have delivered.
        Both 'Me' forms are my side; when they differ, what I actually said wins.
        """
        with self._chat_lock:
            turns = list(self._chat_history)[-self._MEMORY_MAX_TURNS:]
        label = {"interviewer": "Interviewer", "you": "Me", "ai": "Me (draft I prepared)"}
        return "\n".join(f"{label.get(t['speaker'], t['speaker'])}: {t['text']}" for t in turns)

    def _sync_memory(self):
        """Push the current full conversation into the brain before answering."""
        if self._brain:
            self._brain.set_conversation_history(self._conversation_memory())

    def _on_live_transcript(self, source, text):
        """Live (in-progress) speech for a speaker -> chat live line."""
        def _do():
            self._eval_ai_js(f"GhostAI.liveLine({json.dumps(source)}, {json.dumps(text)})")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _on_final_transcript(self, source, text):
        """Finalized speech -> committed chat message (labeled, recorded, saved)."""
        if self._logger:
            self._logger.log_transcript(f"[{source}] {text}", 0.0)
        self._record_chat(source, text)
        def _do():
            self._eval_ai_js(f"GhostAI.commitLine({json.dumps(source)}, {json.dumps(text)})")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _on_audio_chunk_for_logger(self, audio_chunk):
        """Log audio chunks to session."""
        if self._logger:
            self._logger.log_audio_chunk(audio_chunk)

    def _on_user_response(self, text):
        """User's spoken response transcribed from mic."""
        print(f"[GhostAI] User response recorded: {text[:100]}...")
        if self._logger:
            self._logger.log_user_response(text)

    def _on_safety_trigger(self, text):
        """Suspicious question detected - auto-kill and switch to documents."""
        print(f"[GhostAI] SAFETY: Auto-kill triggered by: {text[:80]}")
        if self._logger:
            self._logger.log_error(f"Safety trigger: {text[:100]}", "safety_auto_kill")
        # Execute kill switch on main thread
        def _do():
            self._kill_switch()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _on_pipeline_status(self, status):
        """Pipeline status update."""
        pass  # Logged by pipeline itself

    def _show_followup(self, prediction):
        """Follow-up predictions - not shown in the chat UI (kept as a no-op)."""
        return

    # ── View Switching ──

    def _show_ai_view_threadsafe(self):
        def _do():
            self._show_ai_view()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _show_ai_view(self):
        """Switch to AI view."""
        if self._current_view == "ai":
            return
        self._current_view = "ai"

        # Load AI HTML
        index_path = os.path.join(self._ai_web_dir, "ai.html")
        url = NSURL.fileURLWithPath_(index_path)
        dir_url = NSURL.fileURLWithPath_(self._ai_web_dir)
        self._webview._page_loaded = False
        self._webview._pending_js = []
        self._webview.webview.loadFileURL_allowingReadAccessToURL_(url, dir_url)

        # Replay the saved conversation so switching views never loses the chat.
        with self._chat_lock:
            history = list(self._chat_history)
        if history:
            self._eval_ai_js(f"GhostAI.loadHistory({json.dumps(history)})")

        # Set initial status
        status = "listening" if self._pipeline else "idle"
        self._eval_ai_js(f"GhostAI.setStatus('{status}')")

        # Replay a still-active routing banner so it survives view switches.
        with self._banner_lock:
            pending = self._pending_banner
        if pending:
            msg, kind = pending
            self._eval_ai_js(f"GhostAI.showBanner({json.dumps(msg)}, {json.dumps(kind)})")

    def _show_documents_view(self):
        """Switch back to documents view."""
        if self._current_view == "documents":
            return
        self._current_view = "documents"
        self._webview._page_loaded = False
        self._webview._pending_js = []
        self._webview._load_index()
        self._webview.set_documents(self._documents)

    def _eval_ai_js(self, js):
        """Evaluate JavaScript in the AI view."""
        if self._current_view == "ai":
            self._webview._eval_js(js)

    # ── Live audio indicator (Greenlight / Listening) ──

    # ── Routing banner + per-source meters (Priority 1: bulletproof audio arrival) ──

    def _set_routing_banner(self, message, kind="error"):
        """Show a blocking banner in the AI view (and remember it so it replays on
        view load). kind='error' (red) or 'ok' (green, transient confirmation)."""
        with self._banner_lock:
            self._pending_banner = None if kind == "ok" else (message, kind)
        def _do():
            self._eval_ai_js(f"GhostAI.showBanner({json.dumps(message)}, {json.dumps(kind)})")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _clear_routing_banner(self):
        """Remove the routing banner (capture is confirmed healthy again)."""
        with self._banner_lock:
            self._pending_banner = None
        def _do():
            self._eval_ai_js("GhostAI.hideBanner()")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _on_source_level(self, source, peak):
        """Per-source audio level -> the THEM/YOU meters in the AI view."""
        connected = peak > 0.02
        def _do():
            self._eval_ai_js(
                f"GhostAI.setSourceLevel({json.dumps(source)}, "
                f"{json.dumps(bool(connected))}, {peak:.4f})")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
        self._check_routing_loss(source, peak)

    def _check_routing_loss(self, source, peak):
        """Detect the interviewer feed being dead - both flavors:

        LOST: it worked, then died mid-session (the "worked, then only my voice"
        failure) - the call app switched its speaker off 'Ghost Audio'.

        NEVER: it never worked at all even though a conversation is clearly
        happening. This is the sneaky one: the launch pre-flight only proves that
        SYSTEM audio reaches BlackHole - a call app whose speaker is explicitly
        set to a real device (instead of 'Same as System' / 'Ghost Audio')
        bypasses Ghost entirely and still passes pre-flight.

        Keyed on the INTERVIEWER source only. The mic-activity corroboration on
        the banner keeps it from crying wolf before the call actually starts;
        interviewer-only mode (no mic) gets the softer print-only warning.
        """
        now = time.time()
        if source == "interviewer":
            if peak > 0.006:               # pipeline's "interviewer present" floor
                if not self._iv_ever:
                    print("[GhostAI] 🎧 Audio detected - interviewer capture is live.")
                self._iv_ever = True
                self._iv_last_energy = now
                if self._routing_lost:
                    self._routing_lost = False
                    print("[GhostAI] 🎧 Interviewer audio is back - capture restored.")
                    self._clear_routing_banner()
                return
            # Interviewer silent this tick. One-shot early warning if NOTHING has
            # ever arrived - works in interviewer-only mode too, where there's no
            # mic to corroborate. Print/log only: a red banner 15s into a session
            # where the call simply hasn't started yet would cry wolf.
            if (not self._iv_ever and not self._silence_warned and self._session_start
                    and (now - self._session_start) >= self._NO_AUDIO_WARN_SECONDS):
                self._silence_warned = True
                msg = (f"No interviewer audio captured in the first "
                       f"{int(now - self._session_start)}s. If the interviewer has been "
                       "talking, your call app is likely outputting to a device other "
                       "than 'Ghost Audio' - set its speaker to 'Ghost Audio' (or 'Same "
                       "as System'). (If nobody's spoken yet, ignore this.)")
                print(f"[GhostAI] ⚠️  {msg}")
                if self._logger:
                    self._logger.log_error(msg, "no_audio_watchdog")
            return

        # source == "you": the mic. Track speech-level activity.
        if peak > 0.02:
            self._you_last_energy = now

        # Trip when the mic is clearly picking up a conversation but the call feed
        # is dead - either dead AGAIN (lost) or dead STILL (never).
        lost = (self._iv_ever
                and (now - self._iv_last_energy) >= self._ROUTING_LOSS_SECONDS)
        never = (not self._iv_ever and self._session_start
                 and (now - self._session_start) >= self._ROUTING_LOSS_SECONDS)
        if (not self._routing_lost and (lost or never)
                and (now - self._you_last_energy) <= 10.0):
            self._routing_lost = True
            if lost:
                secs = int(now - self._iv_last_energy)
                msg = (f"The interviewer's audio has stopped reaching Ghost ({secs}s with "
                       f"nothing on the call feed while your mic is active). Their voice is "
                       f"no longer being captured - usually the call app switched its "
                       f"speaker off 'Ghost Audio'. Fix: set the call app's output (and "
                       f"System Settings → Sound → Output) back to 'Ghost Audio'.")
            else:
                msg = ("Your mic is picking up a conversation, but NOTHING from the call "
                       "has ever reached Ghost - the interviewer is NOT being captured. "
                       "Your call app's speaker is almost certainly pinned to a specific "
                       "device instead of 'Ghost Audio' / 'Same as System'. Fix it in the "
                       "call app's audio settings.")
            print(f"[GhostAI] ⚠️  {msg}")
            self._set_routing_banner(msg, "error")
            if self._logger:
                self._logger.log_error(msg, "routing_loss_watchdog")

    def _start_output_watchdog(self):
        """Keep the interviewer capture AND the user's own hearing routed correctly.

        Two distinct failures, checked every 2s:

        1. Default output is no longer 'Ghost Audio' (macOS or the user switched it,
           classically an AirPods reconnect stealing the default). Capture is dead:
           rebuild Ghost for the CURRENT device and take the default back.

        2. Default IS still 'Ghost Audio', but the physical device BAKED INTO the
           aggregate is no longer the right one. An aggregate hard-wires one output
           at creation; macOS never re-points it. When AirPods drop out of a
           Ghost(AirPods) aggregate, the name check alone says "all good" while the
           audio pours into BlackHole only - the user hears NOTHING and, because
           capture still works, no other watchdog fires. And after a rebuild grabs
           the speakers, reconnected AirPods stay silent forever for the same
           reason. The ghost's UID encodes the output UID it was built for
           (ghost_audio_uid_for), so staleness is detectable: compare it against
           the current best real device and rebuild on mismatch. This is the
           actual fix for 'my sound flipped between AirPods and speakers'.

        The mismatch check is debounced (2 consecutive ticks) so Bluetooth
        connect/disconnect flapping doesn't trigger a rebuild storm - rebuilds are
        disruptive (they detach call apps that selected Ghost Audio).

        Deliberately NO verify_blackhole_routing() here: it plays an audible tone
        through the speakers, mid-interview, where the mic can pick it up and send
        it to the interviewer. The pre-flight beep at launch is the only allowed
        one. Post-recovery health is confirmed passively by the level meters and
        _check_routing_loss instead.
        """
        if self._output_watch_running:
            return
        self._output_watch_running = True

        def _loop():
            from ghost.ai.blackhole_setup import (
                get_default_output_name, setup_blackhole, find_output_device,
                ghost_audio_uid_for, find_ghost_audio_device_id, _get_device_uid,
            )
            broken = False
            stale_ticks = 0
            while self._output_watch_running and self._pipeline:
                time.sleep(2.0)
                try:
                    name = get_default_output_name()
                except Exception:
                    continue

                if name == "Ghost Audio":
                    # Failure 2: stale aggregate check.
                    try:
                        _, real_uid, real_name = find_output_device()
                        ghost_id = find_ghost_audio_device_id()
                        ghost_uid = _get_device_uid(ghost_id) if ghost_id else None
                    except Exception:
                        real_uid, ghost_uid, real_name = None, None, None

                    if real_uid and ghost_uid and ghost_uid != ghost_audio_uid_for(real_uid):
                        stale_ticks += 1
                        if stale_ticks < 2:
                            continue  # debounce Bluetooth flapping
                        stale_ticks = 0
                        print(f"[GhostAI] ⚠️  'Ghost Audio' is mirroring to a device that's "
                              f"gone or no longer preferred (current: {real_name}). "
                              f"Rebuilding so you can actually hear the call…")
                        self._set_routing_banner(
                            f"Your audio device changed (now: {real_name}). Ghost is "
                            f"rebuilding its audio routing so you keep hearing the call "
                            f"AND the interviewer keeps being captured…",
                            "error",
                        )
                        broken = True
                        try:
                            setup_blackhole()
                        except Exception as e:
                            print(f"[GhostAI] Ghost Audio rebuild failed: {e}")
                        continue

                    stale_ticks = 0
                    if broken:
                        broken = False
                        print("[GhostAI] 🎧 Output routing healthy again - 'Ghost Audio' "
                              "matches the current device.")
                        self._clear_routing_banner()
                    continue

                # Failure 1: output was switched away from Ghost Audio.
                stale_ticks = 0
                print(f"[GhostAI] ⚠️  Output changed to '{name}' - interviewer no longer "
                      f"captured. Rebuilding 'Ghost Audio' for it and re-routing…")
                self._set_routing_banner(
                    f"Audio output switched to '{name}', so the interviewer is no longer "
                    f"being captured (this happens when AirPods/headphones reconnect). "
                    f"Ghost is re-routing through 'Ghost Audio'…",
                    "error",
                )
                broken = True
                try:
                    # setup_blackhole detects the current device (now '{name}') and
                    # rebuilds Ghost around IT, so the user keeps hearing where they
                    # expect while capture resumes - it does not stomp their choice.
                    setup_blackhole()
                except Exception as e:
                    print(f"[GhostAI] Auto re-route failed: {e}")

        threading.Thread(target=_loop, daemon=True).start()

    def _on_audio_level(self, peak):
        """Drive the AI-view status dot from real incoming audio. Dot ONLY.

        The no-audio and routing-loss watchdogs live in _check_routing_loss,
        keyed on the interviewer source specifically. This overall peak is the
        max of BOTH sources, so keying a watchdog on it meant your own mic
        energy satisfied the "audio seen" check and masked a dead interviewer
        feed - the exact silent-nothing-recorded failure the watchdog existed
        to catch.
        """
        connected = peak > 0.02
        def _do():
            self._eval_ai_js(f"GhostAI.setAudioLevel({json.dumps(bool(connected))}, {peak:.4f})")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    # ── Manual Answer-Now (Option+Space) ──

    def _answer_now(self):
        """Hotkey handler: answer the current question immediately, bypassing silence.

        Switches to the AI view (if needed) and triggers the answer from the
        transcript already captured - same emission path as auto-detection, so it
        runs fine from the key-listener thread.
        """
        if not self._pipeline:
            return
        if self._current_view != "ai":
            self._show_ai_view_threadsafe()
        self._pipeline.answer_now()

    # ── Ask the LLM (main panel) + vision, both answered in the main chat ──

    def _answer_in_main(self, you_text, run):
        """Drive a manual answer into the MAIN chat: show the question as a 'you'
        bubble, then stream a GHOST AI answer. `run(on_token, on_done, on_error)`
        kicks off the streaming call (brain.ask or brain.answer_from_image).

        Epoch-guarded in BOTH directions now: bumping the epoch supersedes any
        in-flight interview answer, and capturing the epoch here means an interview
        answer (or prefetch) that starts LATER supersedes THIS stream too - before,
        a manual stream had no guard, so a prefetch firing mid-vision-answer would
        interleave two token streams into one chat bubble.
        """
        if self._current_view != "ai":
            self._show_ai_view_threadsafe()
        with self._answer_lock:
            self._answer_epoch += 1
            epoch = self._answer_epoch
        # Actually stop the superseded interview stream (the epoch guard only
        # hides its tokens; the stream itself would keep running and billing).
        self._brain.cancel()

        if you_text:
            self._record_chat("you", you_text)
            def _q():
                self._eval_ai_js(f"GhostAI.commitLine('you', {json.dumps(you_text)})")
            NSOperationQueue.mainQueue().addOperationWithBlock_(_q)

        # Feed the full conversation (incl. prior typed/vision/interview turns) as memory.
        self._sync_memory()

        def _start():
            self._eval_ai_js("GhostAI.aiStart()")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_start)

        def on_token(token):
            if epoch != self._answer_epoch:
                return  # superseded by a newer answer - drop stale tokens
            def _do():
                self._eval_ai_js(f"GhostAI.aiToken({json.dumps(token)})")
            NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

        def on_done(full_text):
            if epoch != self._answer_epoch:
                return
            self._record_chat("ai", full_text)
            def _do():
                self._eval_ai_js("GhostAI.aiDone()")
            NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

        def on_error(err):
            if epoch != self._answer_epoch:
                return
            def _do():
                self._eval_ai_js(f"GhostAI.showError({json.dumps(err)})")
            NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

        run(on_token, on_done, on_error)

    def _ask_in_main(self, text):
        """User typed a question into the AI panel's input -> answer in the main chat."""
        if not self._brain:
            return
        self._answer_in_main(
            text,
            lambda t, d, e: self._brain.ask(text, on_token=t, on_done=d, on_error=e),
        )

    def _on_vision(self):
        """Double-tap Right-Shift: screenshot the screen -> vision model -> answer in the
        MAIN chat. For questions shown via screen-share that OCR can't read.

        Gives INSTANT feedback the moment the hotkey fires (a '📸 What's on screen?'
        bubble + a 'Reading the screen…' status) so the user knows the vision model
        was triggered, before the ~1s screenshot+request even starts.
        """
        if not self._brain:
            return

        if self._current_view != "ai":
            self._show_ai_view_threadsafe()
        # Immediate, visible confirmation that Right-Shift x2 registered.
        self._record_chat("you", "📸 What's on screen?")
        def _flash():
            self._eval_ai_js("GhostAI.commitLine('you', \"\\ud83d\\udcf8 What's on screen?\")")
            self._eval_ai_js("GhostAI.setStatus('vision')")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_flash)

        def _work():
            cap = capture_screen_base64()  # whole screen - catches the shared window
            if not cap:
                def _err():
                    self._eval_ai_js(
                        "GhostAI.showError(\"Screen capture failed (check Screen Recording permission)\")")
                NSOperationQueue.mainQueue().addOperationWithBlock_(_err)
                return
            image_b64, media_type = cap
            # Bubble already shown above -> don't duplicate it (you_text=None).
            self._answer_in_main(
                None,
                lambda t, d, e: self._brain.answer_from_image(
                    image_b64, media_type=media_type,
                    on_token=t, on_done=d, on_error=e),
            )

        threading.Thread(target=_work, daemon=True).start()

    def _on_hud_toggle(self):
        """Double-tap Right-Command: show/hide the floating SCREEN box."""
        if self._screen_box:
            self._screen_box.toggle()

    # ── Kill Switch ──

    def _kill_switch_threadsafe(self):
        def _do():
            self._kill_switch()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _kill_switch(self):
        """Instant kill - stop all AI processing, clear screen, return to documents."""
        print("[GhostAI] KILL SWITCH ACTIVATED")

        # Stop the output watchdog thread
        self._output_watch_running = False

        # Cancel Claude streaming (interview + HUD/vision)
        if self._brain:
            self._brain.cancel()
            self._brain.cancel_hud()

        # Hide the floating SCREEN box
        if self._screen_box:
            self._screen_box.hide()

        # Stop audio pipeline
        if self._pipeline:
            self._pipeline.stop()

        # Stop screen-vision - no more reading the screen
        if self._screen_vision:
            self._screen_vision.stop()

        # Clear AI view
        if self._current_view == "ai":
            self._eval_ai_js("GhostAI.clearAll()")

        # Switch to documents
        self._show_documents_view()
        print("[GhostAI] All AI processing stopped. Returned to documents.")

    # ── Standard Ghost callbacks (same as ghost/main.py) ──

    def _auto_load_documents(self):
        search_dirs = []
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        search_dirs.append(os.path.join(app_dir, "documents"))
        search_dirs.append(os.path.join(app_dir, "..", "documents"))
        search_dirs.append(os.path.join(app_dir, "..", "Resources", "documents"))
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        search_dirs.append(os.path.join(project_root, "sample_docs"))
        search_dirs.append(os.path.join(project_root, "documents"))

        for doc_dir in search_dirs:
            if os.path.isdir(doc_dir):
                files = sorted([
                    os.path.join(doc_dir, f) for f in os.listdir(doc_dir)
                    if os.path.isfile(os.path.join(doc_dir, f)) and is_supported(os.path.join(doc_dir, f))
                ])
                if files:
                    print(f"Auto-loading from: {doc_dir}")
                    self._load_files(files[:self.MAX_DOCUMENTS])
                    return

    def _load_files(self, paths):
        errors = []
        for path in paths:
            if self._next_slot > self.MAX_DOCUMENTS:
                errors.append(f"Max {self.MAX_DOCUMENTS} documents reached")
                break
            name = os.path.basename(path)
            if not os.path.isfile(path):
                errors.append(f"File not found: {name}")
                continue
            if not is_supported(path):
                errors.append(f"Unsupported format: {name}")
                continue
            try:
                html = load_document(path)
                ext = get_extension(path)
                self._documents[self._next_slot] = {"name": name, "ext": ext, "html": html}
                print(f"  [{self._next_slot}] {name}")
                self._next_slot += 1
            except Exception as e:
                errors.append(f"Failed to load {name}: {e}")

        self._webview.set_documents(self._documents)
        if errors:
            for err in errors:
                print(f"  WARNING: {err}")

    def _switch_document_threadsafe(self, slot):
        def _do():
            if self._current_view != "documents":
                self._show_documents_view()
            self._webview.display_document(slot)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _go_back_threadsafe(self):
        def _do():
            if self._current_view != "documents":
                self._show_documents_view()
            else:
                self._webview.go_back()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _quit_threadsafe(self):
        def _do():
            self._quit()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _ctrl_toggle_threadsafe(self, pressed):
        def _do():
            self._panel.panel.setIgnoresMouseEvents_(not pressed)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
        # Hold Ctrl to also interact with (scroll) the floating SCREEN box.
        if self._screen_box:
            self._screen_box.set_interactive(pressed)

    def _focus_ask_threadsafe(self):
        """Ctrl+A: focus the 'Ask the LLM' input so the user can type a question
        without the click gymnastics. Makes the panel able to take keystrokes (the
        nonactivating panel becomes key only for the text field, so the app never
        comes to the foreground), then focuses the textarea in the webview. Restored
        to click-through when the box blurs (see the 'ask_blur' message)."""
        def _do():
            if self._current_view != "ai":
                self._show_ai_view()
            self._panel.panel.setIgnoresMouseEvents_(False)
            self._panel.panel.makeKeyAndOrderFront_(None)
            self._eval_ai_js("GhostAI.focusAsk()")
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _on_webview_message(self, body):
        if hasattr(body, "get"):
            action = body.get("action")
            if action == "open":
                slot = body.get("slot")
                self._webview.display_document(slot)
            elif action == "ask":
                # "Ask the LLM" input in the AI panel -> answer in the main chat.
                text = body.get("text") or ""
                if str(text).strip():
                    self._ask_in_main(str(text))
            elif action == "ask_blur":
                # The ask box lost focus (sent / Escape / clicked away) -> restore
                # click-through so the cursor and keystrokes go back to the interview
                # app. (Delivered on the main thread, so this is safe to call directly.)
                self._panel.panel.setIgnoresMouseEvents_(True)

    def _set_opacity(self, value):
        self._panel.set_opacity(value)

    def _show_window(self):
        self._panel.show()

    def _restore_output(self):
        """Restore the user's real audio output on quit, by UID.

        The launch-time AudioObjectID in _prev_output_device is worthless if the
        device replugged since (AirPods that reconnected have a NEW id) - restoring
        by stale id either fails or lands on the wrong device, which is one of the
        ways the user's output ended up somewhere unexpected after a session.
        Resolve the saved UID against the CURRENT device list; if the original
        device is gone entirely, fall back to the best real device available.
        """
        if not self._blackhole_mode:
            return
        try:
            from ghost.ai.blackhole_setup import (
                _get_all_device_ids, _get_device_uid,
                set_default_output_device, find_output_device,
            )
            target_id = None
            if self._prev_output_uid:
                for did in _get_all_device_ids():
                    if _get_device_uid(did) == self._prev_output_uid:
                        target_id = did
                        break
            if target_id is None:
                # Original device is gone (or we never resolved its UID) - route to
                # the best real device instead of leaving the default on Ghost Audio.
                target_id, _, fallback_name = find_output_device()
                if target_id:
                    print(f"[GhostAI] Original output device gone; restoring to {fallback_name}")
            if target_id and set_default_output_device(target_id):
                print("[GhostAI] Restored previous audio output device")
            else:
                print("[GhostAI] Could not restore audio output - pick your device in "
                      "System Settings → Sound → Output")
        except Exception as e:
            print(f"[GhostAI] Could not restore audio output: {e}")

    def _quit(self):
        self._output_watch_running = False
        if self._pipeline:
            self._pipeline.stop()
        if self._screen_vision:
            self._screen_vision.stop()
        # Restore the audio output device we switched away from (BlackHole mode)
        self._restore_output()
        if self._logger:
            self._logger.finalize()
        if self._panel:
            save_state(self._panel.get_window_state())
        if self._keys:
            self._keys.stop()
        NSApplication.sharedApplication().terminate_(None)


def main():
    # Check if --practice flag is present (before full argparse)
    if "--practice" in sys.argv:
        from ghost.ai.practice import main as practice_main
        # Remove --practice from argv so practice's argparse doesn't choke
        sys.argv.remove("--practice")
        practice_main()
        return

    app = GhostAIApp()
    app.run()


if __name__ == "__main__":
    main()