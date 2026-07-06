#!/usr/bin/env python3
"""Ghost Live — Ghost with real-time chat from sender.

Run as: python -m ghost.live.entry --server URL --room CODE
"""

import argparse
import os
import sys
import platform

import AppKit
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSOperationQueue

from ghost.config import get_config, save_state
from ghost.window.panel import GhostPanel
from ghost.window.webview import GhostWebView
from ghost.input.keys import GhostKeyListener
from ghost.ui.tray import GhostTray
from ghost.documents.loader import load_document, get_extension, is_supported
from ghost.live.manager import LiveChatManager


# macOS virtual keycode for '8' key
_VK_8 = 28


class LiveKeyListener(GhostKeyListener):
    """Extends GhostKeyListener with Ctrl+8 to toggle live chat view
    and Ctrl+Shift+S to capture screen text."""

    def __init__(self, on_document_switch, on_back, on_quit, on_ctrl_toggle=None,
                 on_live_toggle=None, on_screen_capture=None):
        super().__init__(on_document_switch, on_back, on_quit, on_ctrl_toggle)
        self._on_live_toggle = on_live_toggle
        self._on_screen_capture = on_screen_capture

    def _on_press(self, key):
        from pynput import keyboard

        # Track modifier state
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
            self._ctrl_pressed = True
            if self._on_ctrl_toggle:
                self._on_ctrl_toggle(True)
            return
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
            self._shift_pressed = True
            return

        # Ctrl+8 -> toggle live chat
        if self._ctrl_pressed and hasattr(key, "vk") and key.vk == _VK_8:
            if self._on_live_toggle:
                self._on_live_toggle()
            return

        # Also check char fallback for Ctrl+8
        if self._ctrl_pressed and hasattr(key, "char") and key.char == "8":
            if self._on_live_toggle:
                self._on_live_toggle()
            return

        # Delegate everything else to the parent
        # We need to re-check since we consumed the modifier tracking above
        # Reset flags so parent doesn't double-track (they were already set)
        # Call parent for the non-modifier key
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
            return
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
            return

        # Escape -> go back to document list (only with Ctrl)
        if self._ctrl_pressed and key == keyboard.Key.esc:
            self._on_back()
            return

        # Ctrl + Shift combos
        if self._ctrl_pressed and self._shift_pressed:
            # Ctrl+Shift+S -> capture screen text
            if hasattr(key, "char") and key.char in ("s", "S"):
                if self._on_screen_capture:
                    self._on_screen_capture()
                return
            if hasattr(key, "vk") and key.vk == 1:  # 'S' keycode
                if self._on_screen_capture:
                    self._on_screen_capture()
                return
            # Ctrl+Shift+Q -> quit Ghost
            if hasattr(key, "char") and key.char in ("q", "Q"):
                self._on_quit()
                return
            if hasattr(key, "vk") and key.vk == 12:
                self._on_quit()
                return

        # Ctrl + number -> switch document (using virtual keycodes)
        from ghost.input.keys import _VK_MAP
        if self._ctrl_pressed and hasattr(key, "vk") and key.vk is not None:
            number = _VK_MAP.get(key.vk)
            if number is not None:
                if 1 <= number <= 7:
                    self._on_document_switch(number)
                    return
                if number == 0:
                    self._on_back()
                    return

        # Fallback: also check key.char
        if self._ctrl_pressed and hasattr(key, "char") and key.char is not None:
            if key.char in "1234567":
                self._on_document_switch(int(key.char))
                return
            if key.char == "0":
                self._on_back()
                return


class LiveGhostApp:
    """Ghost app with Live Chat integration."""

    MAX_DOCUMENTS = 7

    def __init__(self):
        self._documents = {}  # slot -> {name, ext, html}
        self._next_slot = 1
        self._panel = None
        self._webview = None
        self._keys = None
        self._tray = None
        self._live_manager = None
        self._live_showing = False

    def run(self):
        # Parse live chat arguments
        parser = argparse.ArgumentParser(description="Ghost Live - Stealth Document Viewer with Live Chat")
        parser.add_argument("--server", default="https://ghost-relay-4mvn.onrender.com", help="SocketIO server URL")
        parser.add_argument("--room", required=True, help="Room code for encryption and joining")
        args = parser.parse_args()

        # Check macOS version
        mac_ver = platform.mac_ver()[0]
        if mac_ver:
            major = int(mac_ver.split(".")[0])
            if major < 12:
                print(
                    f"WARNING: macOS {mac_ver} detected. "
                    "Stealth mode (sharingType=.none) requires macOS 12+. "
                    "The window will be visible in screen shares."
                )

        # Set up as accessory app (no dock icon, no app switcher)
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        # Create components
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

        # Check Accessibility permission for keyboard shortcuts
        from ghost.main import _check_accessibility
        _check_accessibility()

        # Create key listener with Ctrl+8 for live toggle, Ctrl+Shift+S for screen capture
        self._keys = LiveKeyListener(
            on_document_switch=self._switch_document_threadsafe,
            on_back=self._go_back_threadsafe,
            on_quit=self._quit_threadsafe,
            on_ctrl_toggle=self._ctrl_toggle_threadsafe,
            on_live_toggle=self._live_toggle_threadsafe,
            on_screen_capture=self._screen_capture_threadsafe,
        )
        self._keys.start()

        # Create LiveChatManager
        self._live_manager = LiveChatManager(
            webview_instance=self._webview,
            server_url=args.server,
            room_code=args.room,
        )

        # Load any files passed as extra arguments (filter out --server/--room)
        # argparse already consumes them, so check for leftover files
        # Auto-load from "documents" folder
        self._auto_load_documents()

        # Show the window
        self._panel.show()

        print("Ghost Live is running. Use the menu bar icon to load documents.")
        print("Press Ctrl+1-7 to switch documents, Ctrl+0/Ctrl+Esc to go back.")
        print("Press Ctrl+8 to toggle live chat view.")
        print("Press Ctrl+Shift+S to capture screen text → send to chat.")
        print("Press Ctrl+Shift+Q to quit.")

        # Run the main event loop (blocks here)
        app.run()

    def _load_files(self, paths):
        """Load document files into available slots."""
        errors = []
        loaded = 0

        for path in paths:
            if self._next_slot > self.MAX_DOCUMENTS:
                errors.append(f"Max {self.MAX_DOCUMENTS} documents reached, skipped remaining files")
                break

            name = os.path.basename(path)

            if not os.path.isfile(path):
                errors.append(f"File not found: {name}")
                continue

            if not is_supported(path):
                ext = os.path.splitext(path)[1] or "unknown"
                errors.append(f"Unsupported format ({ext}): {name}")
                continue

            try:
                html = load_document(path)
                ext = get_extension(path)
                self._documents[self._next_slot] = {
                    "name": name,
                    "ext": ext,
                    "html": html,
                }
                print(f"  [{self._next_slot}] {name}")
                self._next_slot += 1
                loaded += 1
            except Exception as e:
                errors.append(f"Failed to load {name}: {e}")

        self._webview.set_documents(self._documents)

        if errors:
            for err in errors:
                print(f"  WARNING: {err}")
            self._webview.show_toast("\n".join(errors))

    def _switch_document_threadsafe(self, slot):
        """Called from pynput background thread -- dispatch to main thread."""
        def _do():
            # If live view is showing, switch back to documents first
            if self._live_showing:
                self._live_showing = False
                self._live_manager.hide()
                self._webview._page_loaded = False
                self._webview._pending_js = []
                self._webview._load_index()
                self._webview.set_documents(self._documents)
            self._webview.display_document(slot)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _go_back_threadsafe(self):
        """Called from pynput background thread -- dispatch to main thread."""
        def _do():
            if self._live_showing:
                # Exit live view, restore document list
                self._live_showing = False
                self._live_manager.hide()
                self._webview._page_loaded = False
                self._webview._pending_js = []
                self._webview._load_index()
                self._webview.set_documents(self._documents)
            else:
                self._webview.go_back()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _ctrl_toggle_threadsafe(self, pressed):
        """When Ctrl is held, enable mouse interaction with Ghost."""
        def _do():
            self._panel.panel.setIgnoresMouseEvents_(not pressed)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _live_toggle_threadsafe(self):
        """Toggle live chat view on Ctrl+8."""
        def _do():
            if self._live_showing:
                # Hide live view, restore documents
                self._live_showing = False
                self._live_manager.hide()
                self._webview._page_loaded = False
                self._webview._pending_js = []
                self._webview._load_index()
                self._webview.set_documents(self._documents)
            else:
                # Show live view
                self._live_showing = True
                self._live_manager.show()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _screen_capture_threadsafe(self):
        """Ctrl+Shift+S — read screen text and send to live chat."""
        import threading

        def _work():
            try:
                from ghost.live.screen_reader import read_focused_window
                text = read_focused_window()
                if not text.strip():
                    print("[Ghost] Screen capture: no text found")
                    return

                if self._live_manager:
                    # Format as screen capture message
                    msg = f"📋 SCREEN CAPTURE:\n\n{text}"
                    self._live_manager.send_message(msg)
                    print(f"[Ghost] Screen text sent to chat ({len(text)} chars)")
                else:
                    print("[Ghost] No live chat connected — cannot send screen text")
            except Exception as e:
                print(f"[Ghost] Screen capture error: {e}")

        # Run on background thread (accessibility API can be slow on complex pages)
        threading.Thread(target=_work, daemon=True).start()

    def _quit_threadsafe(self):
        """Called from pynput background thread -- dispatch to main thread."""
        def _do():
            self._quit()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _on_webview_message(self, body):
        """Handle messages from the web view JavaScript."""
        if hasattr(body, "get"):
            action = body.get("action")
            if action == "live_send":
                text = body.get("text", "")
                if text and self._live_manager:
                    self._live_manager.send_message(text)
            elif action == "open":
                slot = body.get("slot")
                self._webview.display_document(slot)

    def _auto_load_documents(self):
        """Auto-load documents from nearby 'documents' folder."""
        search_dirs = []
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        search_dirs.append(os.path.join(app_dir, "documents"))
        search_dirs.append(os.path.join(app_dir, "..", "documents"))
        search_dirs.append(os.path.join(app_dir, "..", "Resources", "documents"))
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        search_dirs.append(os.path.join(project_root, "sample_docs"))
        search_dirs.append(os.path.join(project_root, "documents"))

        for doc_dir in search_dirs:
            if os.path.isdir(doc_dir):
                files = sorted([
                    os.path.join(doc_dir, f)
                    for f in os.listdir(doc_dir)
                    if os.path.isfile(os.path.join(doc_dir, f)) and is_supported(os.path.join(doc_dir, f))
                ])
                if files:
                    print(f"Auto-loading from: {doc_dir}")
                    self._load_files(files[:self.MAX_DOCUMENTS])
                    return

    def _set_opacity(self, value):
        """Change background opacity."""
        self._panel.set_opacity(value)

    def _show_window(self):
        """Show the Ghost window."""
        self._panel.show()

    def _quit(self):
        """Clean shutdown."""
        if self._live_manager and self._live_manager._client:
            self._live_manager._client.disconnect()
        if self._panel:
            save_state(self._panel.get_window_state())
        if self._keys:
            self._keys.stop()
        NSApplication.sharedApplication().terminate_(None)


def main():
    ghost = LiveGhostApp()
    ghost.run()


if __name__ == "__main__":
    main()
