"""LiveClient — SocketIO receiver for Ghost Live Chat."""

import threading

import socketio

from ghost.crypto import encrypt, decrypt


class LiveClient:
    """Connects to the Ghost relay server via SocketIO and receives messages."""

    def __init__(self, server_url, room_code, on_message, on_edit, on_delete, on_peer_event):
        self._server_url = server_url
        self._room_code = room_code
        self._on_message = on_message
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._on_peer_event = on_peer_event

        self._sio = socketio.Client(reconnection=True, reconnection_attempts=0, request_timeout=30)
        self._register_events()

    def _register_events(self):
        sio = self._sio

        @sio.event
        def connect():
            print("[LiveClient] Connected to server, joining room...")
            sio.emit("join_room", {"code": self._room_code})

        @sio.event
        def disconnect():
            print("[LiveClient] Disconnected")
            if self._on_peer_event:
                self._on_peer_event("disconnected")

        @sio.on("room_joined")
        def on_room_joined(data):
            print(f"[LiveClient] Joined room {data.get('code')}")
            if self._on_peer_event:
                self._on_peer_event("connected")

        @sio.on("error")
        def on_error(data):
            print(f"[LiveClient] Error: {data.get('message')}")
            if self._on_peer_event:
                self._on_peer_event(f"error: {data.get('message')}")

        @sio.on("new_message")
        def on_new_message(data):
            try:
                msg_id = data.get("id", "")
                encrypted_text = data.get("content", "")
                timestamp = data.get("timestamp", "")
                text = decrypt(encrypted_text, self._room_code)
                print(f"[LiveClient] Message received: {text[:50]}...")
                if self._on_message:
                    self._on_message(msg_id, text, timestamp)
            except Exception as e:
                print(f"[LiveClient] Error decrypting message: {e}")

        @sio.on("message_edited")
        def on_message_edited(data):
            try:
                msg_id = data.get("id", "")
                encrypted_text = data.get("content", "")
                new_text = decrypt(encrypted_text, self._room_code)
                if self._on_edit:
                    self._on_edit(msg_id, new_text)
            except Exception as e:
                print(f"[LiveClient] Error decrypting edit: {e}")

        @sio.on("message_deleted")
        def on_message_deleted(data):
            try:
                msg_id = data.get("id", "")
                if self._on_delete:
                    self._on_delete(msg_id)
            except Exception as e:
                print(f"[LiveClient] Error processing delete: {e}")

        @sio.on("peer_connected")
        def on_peer_connected(data=None):
            if self._on_peer_event:
                self._on_peer_event("peer_connected")

        @sio.on("peer_disconnected")
        def on_peer_disconnected(data=None):
            if self._on_peer_event:
                self._on_peer_event("peer_disconnected")

        @sio.on("message_sent")
        def on_message_sent(data):
            # Ack for messages we sent (receiver asking questions)
            pass

    def connect(self):
        """Connect to the server on a daemon background thread."""
        def _connect():
            try:
                self._sio.connect(self._server_url, wait_timeout=30)
                self._sio.wait()
            except Exception as e:
                print(f"[LiveClient] Connection error: {e}, retrying...")
                try:
                    import time
                    time.sleep(3)
                    self._sio.connect(self._server_url, wait_timeout=30)
                    self._sio.wait()
                except Exception as e2:
                    print(f"[LiveClient] Retry failed: {e2}")
                    if self._on_peer_event:
                        self._on_peer_event("error")

        thread = threading.Thread(target=_connect, daemon=True)
        thread.start()

    def send_message(self, text):
        """Send a message back to the sender (receiver asking questions)."""
        try:
            encrypted = encrypt(text, self._room_code)
            self._sio.emit("send_message", {"content": encrypted})
        except Exception as e:
            print(f"[LiveClient] Error sending message: {e}")

    def disconnect(self):
        """Disconnect from the server."""
        try:
            self._sio.disconnect()
        except Exception:
            pass
