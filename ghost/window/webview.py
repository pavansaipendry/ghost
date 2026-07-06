import json
import os

import objc
import AppKit
import WebKit
from Foundation import NSURL
from WebKit import WKWebView, WKWebViewConfiguration, WKUserContentController


class _DroppableWebView(WKWebView):
    """WKWebView subclass that accepts file drops."""

    _on_files_dropped = None

    def draggingEntered_(self, sender):
        return 1  # NSDragOperationCopy

    def draggingUpdated_(self, sender):
        return 1

    def performDragOperation_(self, sender):
        pasteboard = sender.draggingPasteboard()
        items = pasteboard.pasteboardItems()
        paths = []
        if items:
            for item in items:
                url_str = item.stringForType_("public.file-url")
                if url_str:
                    url = NSURL.URLWithString_(url_str)
                    if url and url.path():
                        paths.append(str(url.path()))
        if paths and self._on_files_dropped:
            self._on_files_dropped(paths)
            return True
        return False


# Protocol for receiving messages from JavaScript
WKScriptMessageHandler = objc.protocolNamed("WKScriptMessageHandler")

# Protocol for detecting when page finishes loading
WKNavigationDelegate = objc.protocolNamed("WKNavigationDelegate")


class GhostMessageHandler(AppKit.NSObject, protocols=[WKScriptMessageHandler]):
    """Receives messages from JavaScript via window.webkit.messageHandlers.ghost"""

    def initWithCallback_(self, callback):
        self = objc.super(GhostMessageHandler, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        body = message.body()
        if self._callback:
            self._callback(body)


class GhostNavigationDelegate(AppKit.NSObject, protocols=[WKNavigationDelegate]):
    """Detects when the WKWebView finishes loading a page."""

    def initWithCallback_(self, callback):
        self = objc.super(GhostNavigationDelegate, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def webView_didFinishNavigation_(self, webview, navigation):
        if self._callback:
            self._callback()


class GhostWebView:
    def __init__(self, on_message=None):
        self._on_message = on_message
        self._documents = {}  # slot -> {name, ext, html}
        self._page_loaded = False
        self._pending_js = []  # JS calls queued before page load
        self._web_dir = os.path.join(os.path.dirname(__file__), "..", "ui", "web")
        self._web_dir = os.path.abspath(self._web_dir)

        # Configure WKWebView
        config = WKWebViewConfiguration.alloc().init()

        # Set up message handler for JS -> Python communication
        content_controller = WKUserContentController.alloc().init()
        self._msg_handler = GhostMessageHandler.alloc().initWithCallback_(self._handle_message)
        content_controller.addScriptMessageHandler_name_(self._msg_handler, "ghost")
        config.setUserContentController_(content_controller)

        # Allow file access for local CSS/JS loading
        prefs = config.preferences()
        prefs.setValue_forKey_(True, "allowFileAccessFromFileURLs")

        # Create the WKWebView (droppable subclass for file drag-and-drop)
        self.webview = _DroppableWebView.alloc().initWithFrame_configuration_(
            AppKit.NSMakeRect(0, 0, 500, 700), config
        )
        self.webview.registerForDraggedTypes_(["public.file-url"])

        # Navigation delegate to detect page load completion
        self._nav_delegate = GhostNavigationDelegate.alloc().initWithCallback_(self._on_page_loaded)
        self.webview.setNavigationDelegate_(self._nav_delegate)

        # Transparent background so vibrancy shows through
        self.webview.setValue_forKey_(False, "drawsBackground")

        # Load the index.html
        self._load_index()

    def _load_index(self):
        index_path = os.path.join(self._web_dir, "index.html")
        url = NSURL.fileURLWithPath_(index_path)
        dir_url = NSURL.fileURLWithPath_(self._web_dir)
        self.webview.loadFileURL_allowingReadAccessToURL_(url, dir_url)

    def _on_page_loaded(self):
        """Called when index.html finishes loading. Flush any queued JS calls."""
        self._page_loaded = True
        for js in self._pending_js:
            self.webview.evaluateJavaScript_completionHandler_(js, None)
        self._pending_js.clear()

    def _eval_js(self, js):
        """Evaluate JavaScript, queuing if the page hasn't loaded yet."""
        if self._page_loaded:
            self.webview.evaluateJavaScript_completionHandler_(js, None)
        else:
            self._pending_js.append(js)

    def _handle_message(self, body):
        """Handle messages from JavaScript."""
        if hasattr(body, "get"):
            action = body.get("action")
            if action == "open":
                slot = body.get("slot")
                self.display_document(slot)
            elif action == "back":
                pass  # JS already handles the UI update

        if self._on_message:
            self._on_message(body)

    def set_documents(self, documents):
        """Set the loaded documents. documents = {slot: {name, ext, html}}"""
        self._documents = documents
        # Update JS with document list (no HTML content -- just metadata)
        doc_list = []
        for slot, doc in sorted(self._documents.items()):
            doc_list.append({"slot": slot, "name": doc["name"], "ext": doc["ext"]})
        js = f"Ghost.setDocuments({json.dumps(doc_list)})"
        self._eval_js(js)

    def display_document(self, slot):
        """Display a document by slot number."""
        if slot not in self._documents:
            return
        doc = self._documents[slot]
        # Escape the HTML for embedding in a JS string
        html_escaped = json.dumps(doc["html"])
        name_escaped = json.dumps(doc["name"])
        js = f"Ghost.showDocument({slot}, {name_escaped}, {html_escaped})"
        self._eval_js(js)

    def go_back(self):
        """Return to the document list view."""
        js = "Ghost.goBack()"
        self._eval_js(js)

    def set_on_files_dropped(self, callback):
        """Set callback for drag-and-drop file loading."""
        self.webview._on_files_dropped = callback

    def show_toast(self, message):
        """Show a temporary error/info toast in the UI."""
        msg_escaped = json.dumps(message)
        js = f"Ghost.showToast({msg_escaped})"
        self._eval_js(js)

    def get_native_view(self):
        """Return the underlying WKWebView for embedding in the panel."""
        return self.webview
