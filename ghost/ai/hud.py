"""Ghost SCREEN box — a small floating box on the desktop that shows "what Ghost
sees" (the live screen OCR), separate from the main Ghost panel and INVISIBLE to
screen sharing (sharingType=0).

Display-only: it just renders the latest OCR text, updating in place. Mouse events
pass straight through (it's an overlay, not interactive). Toggle show/hide with the
double-tap Right-Command hotkey.

The class is still named GhostHUD for import stability; it's the screen box.
"""

import json
import os

import AppKit
from AppKit import (
    NSPanel,
    NSColor,
    NSScreen,
    NSMakeRect,
    NSBackingStoreBuffered,
)
from Foundation import NSURL, NSOperationQueue
from WebKit import WKWebView, WKWebViewConfiguration

from ghost.window.webview import GhostNavigationDelegate

# Window style mask bits
_STYLE_TITLED = 1 << 0
_STYLE_UTILITY = 1 << 4
_STYLE_NONACTIVATING = 1 << 7


class GhostHUD:
    """Floating, stealth, display-only box showing the live screen OCR."""

    def __init__(self, width=380, height=300):
        self._page_loaded = False
        self._pending_js = []
        self._visible = False
        self._web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "web"))

        # Top-right corner by default, with a margin off the screen edges.
        screen = NSScreen.mainScreen().frame()
        margin = 48
        x = screen.size.width - width - margin
        y = screen.size.height - height - margin
        frame = NSMakeRect(x, y, width, height)

        style = _STYLE_TITLED | _STYLE_UTILITY | _STYLE_NONACTIVATING
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )

        # Stealth: invisible to screen capture / screen share (macOS 12+).
        if hasattr(self.panel, "setSharingType_"):
            self.panel.setSharingType_(0)

        self.panel.setLevel_(3)                       # float above other windows
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setCollectionBehavior_(1 | 16)     # all Spaces, stays during Exposé
        self.panel.setBecomesKeyOnlyIfNeeded_(True)
        self.panel.setIgnoresMouseEvents_(True)       # display-only overlay; clicks pass through
        self.panel.setTitle_("")
        self.panel.setTitlebarAppearsTransparent_(True)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setOpaque_(False)

        config = WKWebViewConfiguration.alloc().init()
        config.preferences().setValue_forKey_(True, "allowFileAccessFromFileURLs")

        content_view = self.panel.contentView()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(
            content_view.bounds(), config
        )
        self.webview.setAutoresizingMask_(18)
        self._nav_delegate = GhostNavigationDelegate.alloc().initWithCallback_(self._on_loaded)
        self.webview.setNavigationDelegate_(self._nav_delegate)
        self.webview.setValue_forKey_(False, "drawsBackground")
        content_view.addSubview_(self.webview)

        self._load()

    # ── Page loading / JS bridge ──

    def _load(self):
        index = os.path.join(self._web_dir, "hud.html")
        url = NSURL.fileURLWithPath_(index)
        dir_url = NSURL.fileURLWithPath_(self._web_dir)
        self.webview.loadFileURL_allowingReadAccessToURL_(url, dir_url)

    def _on_loaded(self):
        self._page_loaded = True
        for js in self._pending_js:
            self.webview.evaluateJavaScript_completionHandler_(js, None)
        self._pending_js = []

    def _eval(self, js):
        """Run JS on the main thread (safe to call from any thread)."""
        def _do():
            if self._page_loaded:
                self.webview.evaluateJavaScript_completionHandler_(js, None)
            else:
                self._pending_js.append(js)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    # ── JS API (all main-thread-safe) ──

    def set_screen(self, text):
        """Update the displayed OCR text ('what Ghost sees')."""
        self._eval(f"SCREEN.set({json.dumps(text or '')})")

    def status(self, msg):
        self._eval(f"SCREEN.status({json.dumps(msg)})")

    def set_interactive(self, interactive):
        """Toggle mouse interaction. When interactive, the box stops passing mouse
        events through, so you can scroll it (used while Ctrl is held)."""
        def _do():
            self.panel.setIgnoresMouseEvents_(not interactive)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    # ── Window control (main-thread-safe) ──

    def show(self):
        def _do():
            self.panel.orderFront_(None)
            self._visible = True
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def hide(self):
        def _do():
            self.panel.orderOut_(None)
            self._visible = False
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def toggle(self):
        def _do():
            if self._visible:
                self.panel.orderOut_(None)
                self._visible = False
            else:
                self.panel.orderFront_(None)
                self._visible = True
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
