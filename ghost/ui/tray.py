import objc
import AppKit
from AppKit import (
    NSObject,
    NSStatusBar,
    NSMenu,
    NSMenuItem,
    NSOpenPanel,
    NSVariableStatusItemLength,
    NSAlert,
)


class GhostTray(NSObject):

    def init(self):
        self = objc.super(GhostTray, self).init()
        if self is None:
            return None
        self._on_load_documents = None
        self._on_quit = None
        self._on_opacity_change = None
        self._on_show_window = None
        self._status_item = None
        self._opacity = 0.35
        return self

    def setup(self):
        status_bar = NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(NSVariableStatusItemLength)

        button = self._status_item.button()
        button.setTitle_("G")
        button.setToolTip_("Ghost - Stealth Document Viewer")

        menu = NSMenu.alloc().init()

        load_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Load Documents...", "loadDocuments:", ""
        )
        load_item.setTarget_(self)
        menu.addItem_(load_item)

        show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Window", "showWindow:", ""
        )
        show_item.setTarget_(self)
        menu.addItem_(show_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Opacity submenu
        opacity_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Opacity", None, ""
        )
        opacity_submenu = NSMenu.alloc().init()

        for label, val in [("20%", 0.20), ("35%", 0.35), ("50%", 0.50), ("65%", 0.65), ("80%", 0.80), ("100%", 1.0)]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, "setOpacity:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(val)
            opacity_submenu.addItem_(item)

        opacity_item.setSubmenu_(opacity_submenu)
        menu.addItem_(opacity_item)

        menu.addItem_(NSMenuItem.separatorItem())

        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "About Ghost", "showAbout:", ""
        )
        about_item.setTarget_(self)
        menu.addItem_(about_item)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Ghost", "quitApp:", ""
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)

        self._status_item.setMenu_(menu)

    @objc.IBAction
    def loadDocuments_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(True)
        panel.setAllowedFileTypes_(["pdf", "docx", "md", "markdown", "txt"])
        panel.setTitle_("Load Documents into Ghost")
        panel.setPrompt_("Load")

        result = panel.runModal()
        if result == 1:  # NSModalResponseOK
            urls = panel.URLs()
            paths = [str(url.path()) for url in urls]
            if paths and self._on_load_documents:
                self._on_load_documents(paths)

    @objc.IBAction
    def showWindow_(self, sender):
        if self._on_show_window:
            self._on_show_window()

    @objc.IBAction
    def setOpacity_(self, sender):
        val = sender.representedObject()
        if val is not None and self._on_opacity_change:
            self._on_opacity_change(float(val))

    @objc.IBAction
    def showAbout_(self, sender):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Ghost")
        alert.setInformativeText_(
            "Stealth Document Viewer for macOS\n\n"
            "Load documents before a meeting, switch with Ctrl+1-7.\n"
            "Invisible to screen sharing (macOS 12+).\n\n"
            "Shortcuts:\n"
            "  Ctrl+1-7  Open document\n"
            "  Ctrl+0    Back to list\n"
            "  Cmd+F     Search in document\n"
            "  +/-       Adjust font size\n"
            "  Ctrl+Shift+Q  Quit"
        )
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    @objc.IBAction
    def quitApp_(self, sender):
        if self._on_quit:
            self._on_quit()
