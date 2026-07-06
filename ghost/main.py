#!/usr/bin/env python3
"""Ghost - Stealth Document Viewer for macOS"""

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


def _check_accessibility():
    """Check if Accessibility permission is granted. Show dialog if not."""
    import ctypes
    import ctypes.util

    cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
    security = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))

    # AXIsProcessTrusted()
    security.AXIsProcessTrusted.restype = ctypes.c_bool
    trusted = security.AXIsProcessTrusted()

    if not trusted:
        from AppKit import NSAlert, NSAlertStyleWarning
        alert = NSAlert.alloc().init()
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.setMessageText_("Accessibility Permission Required")
        alert.setInformativeText_(
            "Ghost needs Accessibility permission for keyboard shortcuts (Ctrl+1-7).\n\n"
            "Steps:\n"
            "1. Open System Settings\n"
            "2. Go to Privacy & Security → Accessibility\n"
            "3. Click '+' and add this app\n"
            "4. Make sure the toggle is ON\n"
            "5. Restart Ghost\n\n"
            "Without this, you can still use the G menu to load and view documents."
        )
        alert.addButtonWithTitle_("Open System Settings")
        alert.addButtonWithTitle_("Continue Anyway")

        response = alert.runModal()
        if response == 1000:  # First button - Open System Settings
            import subprocess
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])


class GhostApp:
    MAX_DOCUMENTS = 7

    def __init__(self):
        self._documents = {}  # slot -> {name, ext, html}
        self._next_slot = 1
        self._panel = None
        self._webview = None
        self._keys = None
        self._tray = None

    def run(self):
        # Check macOS version for stealth support
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
        _check_accessibility()

        self._keys = GhostKeyListener(
            on_document_switch=self._switch_document_threadsafe,
            on_back=self._go_back_threadsafe,
            on_quit=self._quit_threadsafe,
            on_ctrl_toggle=self._ctrl_toggle_threadsafe,
        )
        self._keys.start()

        # Load any files passed as command line arguments
        if len(sys.argv) > 1:
            paths = [p for p in sys.argv[1:] if os.path.isfile(p) and is_supported(p)]
            if paths:
                self._load_files(paths)

        # Auto-load from "documents" folder next to the app or in Resources
        if not self._documents:
            self._auto_load_documents()

        # Show the window
        self._panel.show()

        print("Ghost is running. Use the menu bar icon to load documents.")
        print("Press Ctrl+1-7 to switch documents, Ctrl+0/Ctrl+Esc to go back.")
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

        # This is safe even before page load -- GhostWebView queues JS calls
        self._webview.set_documents(self._documents)

        # Show errors in UI if any
        if errors:
            for err in errors:
                print(f"  WARNING: {err}")
            self._webview.show_toast("\n".join(errors))

    def _switch_document_threadsafe(self, slot):
        """Called from pynput background thread -- dispatch to main thread."""
        def _do():
            self._webview.display_document(slot)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _go_back_threadsafe(self):
        """Called from pynput background thread -- dispatch to main thread."""
        def _do():
            self._webview.go_back()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _ctrl_toggle_threadsafe(self, pressed):
        """When Ctrl is held, enable mouse interaction with Ghost. When released, pass through."""
        def _do():
            self._panel.panel.setIgnoresMouseEvents_(not pressed)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _quit_threadsafe(self):
        """Called from pynput background thread -- dispatch to main thread."""
        def _do():
            self._quit()
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _on_webview_message(self, body):
        """Handle messages from the web view JavaScript."""
        pass  # Currently handled internally by GhostWebView

    def _auto_load_documents(self):
        """Auto-load documents from nearby 'documents' folder."""
        search_dirs = []
        # Check next to the executable/script
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        search_dirs.append(os.path.join(app_dir, "documents"))
        search_dirs.append(os.path.join(app_dir, "..", "documents"))
        # Check in Resources (for .app bundle)
        search_dirs.append(os.path.join(app_dir, "..", "Resources", "documents"))
        # Check in project root (for dev mode)
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
        """Show the Ghost window (in case it was closed)."""
        self._panel.show()

    def _quit(self):
        """Clean shutdown."""
        # Save window state for next session
        if self._panel:
            save_state(self._panel.get_window_state())
        if self._keys:
            self._keys.stop()
        NSApplication.sharedApplication().terminate_(None)


def main():
    ghost = GhostApp()
    ghost.run()


if __name__ == "__main__":
    main()
