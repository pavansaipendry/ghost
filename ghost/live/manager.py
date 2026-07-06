"""LiveChatManager — bridges LiveClient SocketIO events to the Ghost WKWebView."""

import json
import os

from AppKit import NSOperationQueue

from ghost.live.client import LiveClient


class LiveChatManager:
    """Manages the live chat overlay, message state, and JS bridge."""

    def __init__(self, webview_instance, server_url, room_code):
        self._webview = webview_instance
        self._server_url = server_url
        self._room_code = room_code
        self._messages = []  # [{id, text, timestamp, isOwn}]
        self.is_active = False
        self._has_new = False

        self._web_dir = os.path.join(os.path.dirname(__file__), "web")
        self._web_dir = os.path.abspath(self._web_dir)

        self._client = LiveClient(
            server_url=server_url,
            room_code=room_code,
            on_message=self._on_message,
            on_edit=self._on_edit,
            on_delete=self._on_delete,
            on_peer_event=self._on_peer_event,
        )
        self._client.connect()

    def show(self):
        """Load live.html into the WKWebView and display the live chat."""
        self.is_active = True
        self._has_new = False

        # Load the live chat page
        from Foundation import NSURL
        index_path = os.path.join(self._web_dir, "live.html")
        url = NSURL.fileURLWithPath_(index_path)
        dir_url = NSURL.fileURLWithPath_(self._web_dir)

        # Reset page loaded state so JS calls queue until live.html finishes loading
        self._webview._page_loaded = False
        self._webview._pending_js = []
        self._webview.webview.loadFileURL_allowingReadAccessToURL_(url, dir_url)

        # Push room info and existing messages after page loads
        self._eval_js(
            f"GhostLive.setRoomInfo({json.dumps(self._room_code)}, 'connected')"
        )
        for msg in self._messages:
            self._eval_js(
                f"GhostLive.addMessage({json.dumps(msg['id'])}, "
                f"{json.dumps(msg['text'])}, "
                f"{json.dumps(msg['timestamp'])}, "
                f"{json.dumps(msg['isOwn'])})"
            )

        # Remove the new-message indicator from the DOM
        self._eval_js(
            "var el = document.getElementById('ghost-live-dot'); if(el) el.remove();"
        )

    def hide(self):
        """Mark live view as inactive. The caller restores the document view."""
        self.is_active = False

    def send_message(self, text):
        """Send a message from the receiver back to the sender."""
        self._client.send_message(text)
        # Optimistically add to local state as own message
        import time
        msg = {
            "id": f"own-{int(time.time() * 1000)}",
            "text": text,
            "timestamp": self._iso_now(),
            "isOwn": True,
        }
        self._messages.append(msg)
        if self.is_active:
            self._eval_js(
                f"GhostLive.addMessage({json.dumps(msg['id'])}, "
                f"{json.dumps(msg['text'])}, "
                f"{json.dumps(msg['timestamp'])}, true)"
            )

    # ── SocketIO Callbacks (called from background thread) ──

    def _on_message(self, msg_id, text, timestamp):
        """Handle an incoming message from the sender."""
        msg = {"id": msg_id, "text": text, "timestamp": timestamp, "isOwn": False}
        self._messages.append(msg)
        if self.is_active:
            self._eval_js(
                f"GhostLive.addMessage({json.dumps(msg_id)}, "
                f"{json.dumps(text)}, "
                f"{json.dumps(timestamp)}, false)"
            )
        else:
            self._has_new = True
            self._inject_new_indicator()

    def _on_edit(self, msg_id, new_text):
        """Handle an edited message."""
        for msg in self._messages:
            if msg["id"] == msg_id:
                msg["text"] = new_text
                break
        if self.is_active:
            self._eval_js(
                f"GhostLive.editMessage({json.dumps(msg_id)}, {json.dumps(new_text)})"
            )

    def _on_delete(self, msg_id):
        """Handle a deleted message."""
        self._messages = [m for m in self._messages if m["id"] != msg_id]
        if self.is_active:
            self._eval_js(f"GhostLive.deleteMessage({json.dumps(msg_id)})")

    def _on_peer_event(self, event):
        """Handle peer connection/disconnection events."""
        if self.is_active:
            status = event if event in ("connected", "disconnected", "error") else "connecting"
            self._eval_js(
                f"GhostLive.setRoomInfo({json.dumps(self._room_code)}, {json.dumps(status)})"
            )

    # ── Helpers ──

    def _eval_js(self, js):
        """Dispatch JavaScript evaluation to the main thread."""
        def _do():
            self._webview._eval_js(js)
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do)

    def _inject_new_indicator(self):
        """Inject a pulsing blue dot into the current document list page."""
        js = (
            "if (!document.getElementById('ghost-live-dot')) {"
            "  var dot = document.createElement('div');"
            "  dot.id = 'ghost-live-dot';"
            "  dot.style.cssText = "
            "    'position:fixed;top:10px;right:10px;width:10px;height:10px;"
            "     border-radius:50%;background:#8AB4F8;z-index:1000;"
            "     animation:ghost-live-pulse 1.5s ease-in-out infinite;';"
            "  var style = document.createElement('style');"
            "  style.textContent = '@keyframes ghost-live-pulse {"
            "    0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.4;transform:scale(0.8)}}';"
            "  document.head.appendChild(style);"
            "  document.body.appendChild(dot);"
            "}"
        )
        self._eval_js(js)

    @staticmethod
    def _iso_now():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
