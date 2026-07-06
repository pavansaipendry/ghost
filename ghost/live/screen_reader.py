"""Screen Reader — extracts text from the focused browser window.

Primary method: AppleScript to execute JavaScript in Chrome/Safari/Arc/Brave
and get document.body.innerText. This bypasses CSS user-select:none and works
with any website (HackerRank, LeetCode, CoderPad, etc.)

Fallback: macOS Accessibility API (AXUIElement) for non-browser apps.

Usage:
    from ghost.live.screen_reader import read_focused_window
    text = read_focused_window()
"""

import subprocess

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXIsProcessTrusted,
)


def is_accessibility_enabled() -> bool:
    """Check if Accessibility permission is granted."""
    return AXIsProcessTrusted()


def read_focused_window() -> str:
    """Read all text from the currently focused window.

    For browsers (Chrome, Safari, Arc, Brave, Edge): uses AppleScript to
    execute JavaScript and get the page text directly.

    For other apps: falls back to the macOS Accessibility API.
    """
    frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
    if frontmost is None:
        print("[ScreenReader] No frontmost application")
        return ""

    app_name = frontmost.localizedName()
    bundle_id = frontmost.bundleIdentifier() or ""
    pid = frontmost.processIdentifier()
    print(f"[ScreenReader] Focused app: {app_name} (PID {pid})")

    # Try browser-specific extraction first
    browser_text = _read_browser(app_name, bundle_id)
    if browser_text:
        return browser_text

    # Fallback: Accessibility API for non-browser apps
    print("[ScreenReader] Not a supported browser, trying Accessibility API...")
    return _read_via_accessibility(pid, app_name)


def _read_browser(app_name: str, bundle_id: str) -> str:
    """Extract page text from a browser using AppleScript + JavaScript."""

    # Map bundle IDs / app names to their AppleScript application name
    chrome_ids = {
        "com.google.Chrome", "com.google.Chrome.canary",
        "com.brave.Browser", "com.microsoft.edgemac",
    }
    chrome_names = {"Google Chrome", "Brave Browser", "Microsoft Edge", "Google Chrome Canary"}

    safari_ids = {"com.apple.Safari", "com.apple.SafariTechnologyPreview"}
    safari_names = {"Safari", "Safari Technology Preview"}

    arc_ids = {"company.thebrowser.Browser"}
    arc_names = {"Arc"}

    if bundle_id in chrome_ids or app_name in chrome_names:
        return _read_chrome(app_name)
    elif bundle_id in arc_ids or app_name in arc_names:
        return _read_chrome("Arc")  # Arc supports Chrome-style AppleScript
    elif bundle_id in safari_ids or app_name in safari_names:
        return _read_safari()
    else:
        return ""


def _read_chrome(app_name: str) -> str:
    """Read page text from Chrome-based browser via AppleScript."""
    script = f'''
    tell application "{app_name}"
        set pageText to execute front window's active tab javascript "document.body.innerText"
        return pageText
    end tell
    '''
    text = _run_applescript(script)
    if text:
        print(f"[ScreenReader] Chrome extraction: {len(text)} chars")
        return _filter_problem_content(text)
    return ""


def _read_safari() -> str:
    """Read page text from Safari via AppleScript."""
    script = '''
    tell application "Safari"
        set pageText to do JavaScript "document.body.innerText" in front document
        return pageText
    end tell
    '''
    text = _run_applescript(script)
    if text:
        print(f"[ScreenReader] Safari extraction: {len(text)} chars")
        return _filter_problem_content(text)
    return ""


def _filter_problem_content(text: str) -> str:
    """Filter raw page text to extract just the problem content.

    Looks for problem markers (title, description, examples, constraints)
    and strips out navigation, comments, sidebar, and other noise.
    """
    import re
    lines = text.split('\n')

    # Try to find the problem section by known markers
    # LeetCode: problem number + title pattern like "3548. Equal Sum Grid..."
    # HackerRank: "Problem", "Challenge"
    # General: "Example", "Input:", "Output:", "Constraints:"
    start_patterns = [
        re.compile(r'^\d+\.\s+\w'),              # "3548. Equal Sum..."
        re.compile(r'^Problem\b', re.I),          # "Problem Statement"
        re.compile(r'^Challenge\b', re.I),        # HackerRank
    ]

    end_patterns = [
        re.compile(r'^Discussion\s*\(\d+\)', re.I),   # LeetCode discussions
        re.compile(r'^Seen this question', re.I),      # LeetCode
        re.compile(r'^Similar Questions', re.I),
        re.compile(r'^Related Topics', re.I),
        re.compile(r'^Comments?\s*$', re.I),
        re.compile(r'^Editorial\s*$', re.I),           # Second "Editorial" after content
        re.compile(r'^\d+\s+Online\s*$'),              # "2504 Online"
        re.compile(r'^Copyright\b', re.I),
        re.compile(r'^Sign Out\s*$', re.I),
    ]

    # Find start: first line matching a start pattern
    start_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat in start_patterns:
            if pat.search(stripped):
                start_idx = i
                break
        if start_idx > 0:
            break

    # Find end: first line after start matching an end pattern
    end_idx = len(lines)
    # Skip a few lines after start before looking for end markers
    search_from = min(start_idx + 5, len(lines))
    for i in range(search_from, len(lines)):
        stripped = lines[i].strip()
        for pat in end_patterns:
            if pat.search(stripped):
                end_idx = i
                break
        if end_idx < len(lines):
            break

    # Extract the problem section
    problem_lines = lines[start_idx:end_idx]

    # Remove empty noise lines and excessive whitespace
    cleaned = []
    blank_count = 0
    for line in problem_lines:
        stripped = line.strip()
        if not stripped:
            blank_count += 1
            if blank_count <= 2:  # Allow max 2 consecutive blank lines
                cleaned.append('')
        else:
            blank_count = 0
            cleaned.append(stripped)

    result = '\n'.join(cleaned).strip()

    if len(result) < 50:
        # Filtering removed too much — return full cleaned text
        return _clean_text(text)

    print(f"[ScreenReader] Filtered to {len(result)} chars (from {len(text)})")
    return result


def _run_applescript(script: str) -> str:
    """Execute an AppleScript and return its output."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            stderr = result.stderr.strip()
            if "not allowed" in stderr.lower() or "javascript" in stderr.lower():
                print(f"[ScreenReader] Enable 'Allow JavaScript from Apple Events':")
                print(f"[ScreenReader]   Chrome → View → Developer → Allow JavaScript from Apple Events")
            else:
                print(f"[ScreenReader] AppleScript error: {stderr[:200]}")
            return ""
    except subprocess.TimeoutExpired:
        print("[ScreenReader] AppleScript timed out")
        return ""
    except Exception as e:
        print(f"[ScreenReader] AppleScript exception: {e}")
        return ""


def _clean_text(text: str) -> str:
    """Clean extracted text: remove excessive whitespace, cap length."""
    # Collapse multiple blank lines into one
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # Cap at 8000 chars
    if len(text) > 8000:
        text = text[:8000] + "\n... (truncated)"

    return text


# ── Accessibility API Fallback (for non-browser apps) ──

def _read_via_accessibility(pid: int, app_name: str) -> str:
    """Read text via macOS Accessibility API. Used for non-browser apps."""
    ax_app = AXUIElementCreateApplication(pid)

    err, focused_window = AXUIElementCopyAttributeValue(
        ax_app, "AXFocusedWindow", None
    )
    if err != 0 or focused_window is None:
        err, windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
        if err != 0 or not windows or len(windows) == 0:
            print(f"[ScreenReader] No windows for {app_name}")
            return ""
        focused_window = windows[0]

    texts = []
    _extract_text(focused_window, texts)

    seen = set()
    unique = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    result = "\n".join(unique)
    if len(result) > 8000:
        result = result[:8000] + "\n... (truncated)"

    print(f"[ScreenReader] Accessibility: {len(unique)} text blocks ({len(result)} chars)")
    return result


def _extract_text(element, texts, depth=0):
    """Recursively extract text from an AXUIElement tree."""
    if depth > 100:
        return

    err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
    role_str = str(role) if err == 0 and role else ""

    skip_roles = {"AXMenuBar", "AXMenu", "AXMenuItem", "AXToolbar", "AXScrollBar"}
    if role_str in skip_roles:
        return

    err, value = AXUIElementCopyAttributeValue(element, "AXValue", None)
    if err == 0 and value and isinstance(value, str):
        cleaned = value.strip()
        if cleaned and len(cleaned) > 1:
            texts.append(cleaned)

    if role_str in ("AXHeading", "AXStaticText", "AXLink", "AXCell"):
        err, title = AXUIElementCopyAttributeValue(element, "AXTitle", None)
        if err == 0 and title and isinstance(title, str):
            cleaned = title.strip()
            if cleaned and len(cleaned) > 1 and (not texts or texts[-1] != cleaned):
                texts.append(cleaned)

    err, children = AXUIElementCopyAttributeValue(element, "AXChildren", None)
    if err == 0 and children:
        for child in children:
            _extract_text(child, texts, depth + 1)
