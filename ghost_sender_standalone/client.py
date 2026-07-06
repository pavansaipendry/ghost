"""Socket.IO chat client with end-to-end encryption."""

import threading

import socketio
from crypto import encrypt, decrypt


class ChatClient:
    """Thin wrapper around a Socket.IO client for encrypted chat."""

    def __init__(self, server_url, on_message=None, on_edit=None,
                 on_delete=None, on_peer_event=None):
        self.server_url = server_url
        self._on_message = on_message
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._on_peer_event = on_peer_event
        self.room_code = None
        self._sio = socketio.Client(reconnection=True, request_timeout=30)
        self._connected_event = threading.Event()
        self._room_created_event = threading.Event()
        self._room_joined_event = threading.Event()
        self._send_response_event = threading.Event()
        self._last_send_id = None
        self._register_handlers()

    def _register_handlers(self):
        sio = self._sio

        @sio.event
        def connect():
            self._connected_event.set()

        @sio.event
        def disconnect():
            if self._on_peer_event:
                self._on_peer_event("disconnected_self")

        @sio.on("room_created")
        def on_room_created(data):
            self.room_code = data.get("room_code") or data.get("code")
            self._room_created_event.set()

        @sio.on("room_joined")
        def on_room_joined(data):
            self.room_code = data.get("room_code") or data.get("code") or self.room_code
            self._room_joined_event.set()

        @sio.on("new_message")
        def on_new_message(data):
            if self._on_message and self.room_code:
                try:
                    text = decrypt(data["content"], self.room_code)
                except Exception:
                    text = "[decryption failed]"
                self._on_message(data.get("id"), text, data.get("timestamp"), data.get("sender"))

        @sio.on("message_edited")
        def on_message_edited(data):
            if self._on_edit and self.room_code:
                try:
                    text = decrypt(data["content"], self.room_code)
                except Exception:
                    text = "[decryption failed]"
                self._on_edit(data.get("id"), text)

        @sio.on("message_deleted")
        def on_message_deleted(data):
            if self._on_delete:
                self._on_delete(data.get("id"))

        @sio.on("peer_connected")
        def on_peer_connected(data=None):
            if self._on_peer_event:
                self._on_peer_event("connected")

        @sio.on("peer_disconnected")
        def on_peer_disconnected(data=None):
            if self._on_peer_event:
                self._on_peer_event("disconnected")

        @sio.on("message_sent")
        def on_message_sent(data):
            self._last_send_id = data.get("id")
            self._send_response_event.set()

    def connect(self):
        t = threading.Thread(target=self._connect_worker, daemon=True)
        t.start()

    def _connect_worker(self):
        try:
            self._sio.connect(self.server_url, wait_timeout=30)
            self._connected_event.set()
        except Exception as exc:
            print(f"[ChatClient] connection failed: {exc}")
            try:
                import time
                time.sleep(3)
                self._sio.connect(self.server_url, wait_timeout=30)
                self._connected_event.set()
            except Exception as exc2:
                print(f"[ChatClient] retry failed: {exc2}")

    def create_room(self):
        if not self._connected_event.wait(timeout=30):
            return None
        self._room_created_event.clear()
        self._sio.emit("create_room", {})
        if self._room_created_event.wait(timeout=15):
            return self.room_code
        return None

    def join_room(self, code):
        if not self._connected_event.wait(timeout=30):
            return False
        self._room_joined_event.clear()
        self.room_code = code
        self._sio.emit("join_room", {"code": code})
        return self._room_joined_event.wait(timeout=15)

    def send_message(self, text):
        if not self.room_code:
            return None
        encrypted = encrypt(text, self.room_code)
        self._send_response_event.clear()
        self._last_send_id = None
        self._sio.emit("send_message", {"content": encrypted})
        if self._send_response_event.wait(timeout=10):
            return self._last_send_id
        return None

    def edit_message(self, msg_id, new_text):
        if not self.room_code:
            return
        encrypted = encrypt(new_text, self.room_code)
        self._sio.emit("edit_message", {"id": msg_id, "content": encrypted})

    def delete_message(self, msg_id):
        self._sio.emit("delete_message", {"id": msg_id})

    def disconnect(self):
        try:
            self._sio.disconnect()
        except Exception:
            pass
