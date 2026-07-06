import objc
import AppKit
from AppKit import (
    NSPanel,
    NSVisualEffectView,
    NSFloatingWindowLevel,
    NSColor,
    NSScreen,
    NSMakeRect,
    NSMakeSize,
    NSBackingStoreBuffered,
)

from ghost.config import get_config


class _GhostPanel(NSPanel):
    """NSPanel subclass that ignores Escape, supports drag-and-drop,
    and is completely invisible to cursor management."""

    _on_files_dropped = None

    def cancelOperation_(self, sender):
        pass

    def draggingEntered_(self, sender):
        return 1

    def performDragOperation_(self, sender):
        pasteboard = sender.draggingPasteboard()
        items = pasteboard.pasteboardItems()
        paths = []
        if items:
            for item in items:
                url_str = item.stringForType_("public.file-url")
                if url_str:
                    from Foundation import NSURL
                    url = NSURL.URLWithString_(url_str)
                    if url and url.path():
                        paths.append(str(url.path()))
        if paths and self._on_files_dropped:
            self._on_files_dropped(paths)
            return True
        return False


_STYLE_TITLED = 1 << 0
_STYLE_CLOSABLE = 1 << 1
_STYLE_RESIZABLE = 1 << 3
_STYLE_UTILITY = 1 << 4
_STYLE_NONACTIVATING = 1 << 7

_MATERIAL_DARK = 2
_BLENDING_BEHIND_WINDOW = 0
_STATE_ACTIVE = 1


class GhostPanel:
    def __init__(self):
        cfg = get_config()["window"]
        width = cfg.get("width", 500)
        height = cfg.get("height", 700)
        opacity = cfg.get("opacity", 0.35)

        # Clamp everything to the VISIBLE screen (excludes the menu bar and Dock) so
        # the window can never be taller/wider than what's on-screen and is always
        # positioned fully on-screen. A full-height or off-screen window (which a bad
        # saved state can produce) puts a resize edge past the screen boundary where
        # it can't be grabbed — which is why the height couldn't be reduced.
        vf = NSScreen.mainScreen().visibleFrame()
        self._min_w, self._min_h = 320, 240

        width = max(self._min_w, min(width, vf.size.width))
        height = max(self._min_h, min(height, vf.size.height))

        x = cfg.get("x", -1)
        y = cfg.get("y", -1)
        if x < 0:
            x = vf.origin.x + (vf.size.width - width) / 2
        if y < 0:
            y = vf.origin.y + (vf.size.height - height) / 2
        # Keep the whole window inside the visible area so every edge stays grabbable.
        x = max(vf.origin.x, min(x, vf.origin.x + vf.size.width - width))
        y = max(vf.origin.y, min(y, vf.origin.y + vf.size.height - height))

        frame = NSMakeRect(x, y, width, height)

        style = _STYLE_TITLED | _STYLE_CLOSABLE | _STYLE_RESIZABLE | _STYLE_UTILITY | _STYLE_NONACTIVATING

        self.panel = _GhostPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )

        # Resizable within sane bounds: at least usable, at most the visible screen —
        # so a drag can always shrink the height and the resize handles stay on-screen.
        self.panel.setContentMinSize_(NSMakeSize(self._min_w, self._min_h))
        self.panel.setContentMaxSize_(NSMakeSize(vf.size.width, vf.size.height))

        # Stealth: invisible to screen capture (macOS 12+)
        if hasattr(self.panel, "setSharingType_"):
            self.panel.setSharingType_(0)

        # Floating above other windows
        self.panel.setLevel_(3)

        # Don't hide when app loses focus
        self.panel.setHidesOnDeactivate_(False)

        # Allow dragging from anywhere on the window background
        self.panel.setMovableByWindowBackground_(True)

        # Visible on all Spaces/desktops, stays on top during Expose
        self.panel.setCollectionBehavior_(1 | 16)

        # Allow key events when not the key window
        self.panel.setBecomesKeyOnlyIfNeeded_(True)

        # Disable cursor rects
        self.panel.disableCursorRects()

        # Ignore mouse events by default — cursor passes through to background app
        # User holds Ctrl to interact with Ghost (scroll, click)
        self.panel.setIgnoresMouseEvents_(True)

        # Title bar
        self.panel.setTitle_("Ghost")
        self.panel.setTitleVisibility_(1)
        self.panel.setTitlebarAppearsTransparent_(True)

        # Background: translucent dark vibrancy
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setOpaque_(False)

        content_view = self.panel.contentView()

        vibrancy = NSVisualEffectView.alloc().initWithFrame_(content_view.bounds())
        vibrancy.setAutoresizingMask_(18)
        vibrancy.setMaterial_(_MATERIAL_DARK)
        vibrancy.setBlendingMode_(_BLENDING_BEHIND_WINDOW)
        vibrancy.setState_(_STATE_ACTIVE)
        vibrancy.setAlphaValue_(opacity)

        content_view.addSubview_(vibrancy)

        self._vibrancy = vibrancy
        self._opacity = opacity

        # Register for file drag-and-drop
        self.panel.registerForDraggedTypes_(["public.file-url"])

    def set_webview(self, webview):
        """Embed a WKWebView into the panel on top of the vibrancy layer."""
        content_view = self.panel.contentView()
        webview.setFrame_(content_view.bounds())
        webview.setAutoresizingMask_(18)
        content_view.addSubview_(webview)

    def show(self):
        self.panel.makeKeyAndOrderFront_(None)

    def hide(self):
        self.panel.orderOut_(None)

    def set_on_files_dropped(self, callback):
        """Set callback for drag-and-drop file loading."""
        self.panel._on_files_dropped = callback

    def get_window_state(self):
        """Return current window position, size, and opacity for persistence."""
        frame = self.panel.frame()
        return {
            "x": float(frame.origin.x),
            "y": float(frame.origin.y),
            "width": float(frame.size.width),
            "height": float(frame.size.height),
            "opacity": self._opacity,
        }

    def set_opacity(self, value):
        self._opacity = max(0.1, min(1.0, value))
        self._vibrancy.setAlphaValue_(self._opacity)
