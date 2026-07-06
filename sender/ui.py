"""Tkinter-based Sender UI for the Ghost encrypted chat."""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Theme constants
# ---------------------------------------------------------------------------
BG = "#1e1e1e"
BG_SECONDARY = "#252526"
BG_INPUT = "#2d2d30"
FG = "#e8e8e8"
FG_DIM = "#888888"
ACCENT = "#8AB4F8"
SENT_BG = "#2a3a50"
PEER_BG = "#2d2d30"
GREEN = "#4EC9B0"
RED = "#F44747"


class SenderUI:
    """Build and manage the Sender chat interface."""

    def __init__(self, root: tk.Tk, client):
        self.root = root
        self.client = client
        self._msg_tags: dict[str, dict] = {}  # msg_id -> {start, end, text, own}
        self._own_ids: set[str] = set()

        # Wire client callbacks (thread-safe via root.after).
        client._on_message = self._cb_new_message
        client._on_edit = self._cb_edit
        client._on_delete = self._cb_delete
        client._on_peer_event = self._cb_peer_event

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TButton", background=BG_SECONDARY, foreground=FG,
                         borderwidth=0, focuscolor=ACCENT)
        style.map("TButton",
                   background=[("active", ACCENT)],
                   foreground=[("active", "#000000")])
        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG,
                         insertcolor=FG, borderwidth=0)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Accent.TButton", background=ACCENT, foreground="#000000")
        style.map("Accent.TButton",
                   background=[("active", "#6fa1e8")])

        # ---- Top bar (room controls) ----
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=10, pady=(10, 5))

        ttk.Button(top, text="Create Room", style="Accent.TButton",
                   command=self._on_create_room).pack(side=tk.LEFT, padx=(0, 5))

        self._join_entry = ttk.Entry(top, width=14)
        self._join_entry.pack(side=tk.LEFT, padx=(0, 5))
        self._join_entry.insert(0, "Room code...")
        self._join_entry.bind("<FocusIn>", self._clear_placeholder)

        ttk.Button(top, text="Join Room",
                   command=self._on_join_room).pack(side=tk.LEFT, padx=(0, 10))

        # Connection status dot
        self._status_canvas = tk.Canvas(top, width=14, height=14,
                                        bg=BG, highlightthickness=0)
        self._status_canvas.pack(side=tk.RIGHT)
        self._status_dot = self._status_canvas.create_oval(2, 2, 12, 12, fill=RED,
                                                            outline="")

        # Room code label
        self._room_label = tk.Label(self.root, text="No room", font=("Helvetica", 24, "bold"),
                                    bg=BG, fg=ACCENT)
        self._room_label.pack(pady=(0, 5))

        # ---- Chat area ----
        chat_frame = ttk.Frame(self.root)
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        self._chat = tk.Text(chat_frame, wrap=tk.WORD, state=tk.DISABLED,
                             bg=BG_SECONDARY, fg=FG, font=("Menlo", 13),
                             relief=tk.FLAT, padx=8, pady=8,
                             selectbackground=ACCENT, selectforeground="#000",
                             cursor="arrow")
        scrollbar = ttk.Scrollbar(chat_frame, command=self._chat.yview)
        self._chat.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._chat.tag_configure("timestamp", foreground=FG_DIM)
        self._chat.tag_configure("you_label", foreground=ACCENT, font=("Menlo", 13, "bold"))
        self._chat.tag_configure("peer_label", foreground=GREEN, font=("Menlo", 13, "bold"))
        self._chat.tag_configure("sent_bg", background=SENT_BG)
        self._chat.tag_configure("peer_bg", background=PEER_BG)
        self._chat.tag_configure("deleted", foreground=FG_DIM, overstrike=True)
        self._chat.tag_configure("system", foreground=FG_DIM, justify=tk.CENTER,
                                 font=("Menlo", 11, "italic"))

        # Bind double-click and right-click for edit/delete.
        self._chat.bind("<Double-Button-1>", self._on_double_click)
        self._chat.bind("<Button-2>", self._on_right_click)   # macOS right-click
        self._chat.bind("<Control-Button-1>", self._on_right_click)

        # ---- Input area ----
        input_frame = ttk.Frame(self.root)
        input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self._input = tk.Text(input_frame, height=2, wrap=tk.WORD,
                              bg=BG_INPUT, fg=FG, font=("Menlo", 13),
                              relief=tk.FLAT, insertbackground=FG,
                              padx=6, pady=6)
        self._input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Shift-Return>", self._on_shift_enter)

        ttk.Button(input_frame, text="Send", style="Accent.TButton",
                   command=self._do_send).pack(side=tk.RIGHT)

        # Context menu
        self._ctx_menu = tk.Menu(self.root, tearoff=0, bg=BG_SECONDARY, fg=FG,
                                 activebackground=ACCENT, activeforeground="#000")
        self._ctx_menu.add_command(label="Edit", command=self._ctx_edit)
        self._ctx_menu.add_command(label="Delete", command=self._ctx_delete)
        self._ctx_target_id: str | None = None

    # ------------------------------------------------------------------
    # Placeholder helper
    # ------------------------------------------------------------------
    def _clear_placeholder(self, _event=None):
        if self._join_entry.get() == "Room code...":
            self._join_entry.delete(0, tk.END)

    # ------------------------------------------------------------------
    # Room actions
    # ------------------------------------------------------------------
    def _on_create_room(self):
        def _work():
            code = self.client.create_room()
            if code:
                self.root.after(0, lambda: self._set_room(code))
            else:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", "Failed to create room."))
        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _on_join_room(self):
        code = self._join_entry.get().strip()
        if not code or code == "Room code...":
            return

        def _work():
            ok = self.client.join_room(code)
            if ok:
                self.root.after(0, lambda: self._set_room(code))
            else:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", "Failed to join room."))
        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _set_room(self, code: str):
        self._room_label.config(text=code)
        self._status_canvas.itemconfig(self._status_dot, fill=GREEN)
        self._append_system(f"Connected to room {code}")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def _on_enter(self, event):
        self._do_send()
        return "break"  # prevent newline

    def _on_shift_enter(self, _event):
        pass  # allow default newline insertion

    def _do_send(self):
        text = self._input.get("1.0", tk.END).strip()
        if not text:
            return
        self._input.delete("1.0", tk.END)

        def _work():
            msg_id = self.client.send_message(text)
            if msg_id:
                self.root.after(0, lambda: self._append_message(
                    msg_id, text, datetime.now().strftime("%H:%M"), own=True))
        import threading
        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------------
    # Chat display helpers
    # ------------------------------------------------------------------
    def _append_message(self, msg_id, text, timestamp, own=False, sender=None):
        self._chat.configure(state=tk.NORMAL)
        start_idx = self._chat.index(tk.END)

        ts = timestamp if timestamp else datetime.now().strftime("%H:%M")
        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts).strftime("%H:%M")

        label = "You" if own else "Peer"
        label_tag = "you_label" if own else "peer_label"
        line_tag = f"msg_{msg_id}" if msg_id else ""
        bg_tag = "sent_bg" if own else "peer_bg"

        self._chat.insert(tk.END, f"[{ts}] ", ("timestamp", line_tag, bg_tag))
        self._chat.insert(tk.END, f"{label}: ", (label_tag, line_tag, bg_tag))
        self._chat.insert(tk.END, f"{text}\n", (line_tag, bg_tag))

        end_idx = self._chat.index(tk.END)
        self._chat.configure(state=tk.DISABLED)
        self._chat.see(tk.END)

        if msg_id:
            self._msg_tags[msg_id] = {
                "start": start_idx,
                "end": end_idx,
                "text": text,
                "own": own,
            }
            if own:
                self._own_ids.add(msg_id)

    def _append_system(self, text: str):
        self._chat.configure(state=tk.NORMAL)
        self._chat.insert(tk.END, f"{text}\n", ("system",))
        self._chat.configure(state=tk.DISABLED)
        self._chat.see(tk.END)

    # ------------------------------------------------------------------
    # Edit / Delete via double-click and context menu
    # ------------------------------------------------------------------
    def _msg_id_at(self, index) -> str | None:
        """Return the message id whose tag covers *index*, if any."""
        tags = self._chat.tag_names(index)
        for t in tags:
            if t.startswith("msg_"):
                mid = t[4:]
                if mid in self._own_ids:
                    return mid
        return None

    def _on_double_click(self, event):
        idx = self._chat.index(f"@{event.x},{event.y}")
        mid = self._msg_id_at(idx)
        if mid:
            self._start_edit(mid)

    def _on_right_click(self, event):
        idx = self._chat.index(f"@{event.x},{event.y}")
        mid = self._msg_id_at(idx)
        if mid:
            self._ctx_target_id = mid
            self._ctx_menu.tk_popup(event.x_root, event.y_root)

    def _ctx_edit(self):
        if self._ctx_target_id:
            self._start_edit(self._ctx_target_id)

    def _ctx_delete(self):
        if self._ctx_target_id:
            mid = self._ctx_target_id
            self.client.delete_message(mid)
            self._mark_deleted(mid)

    def _start_edit(self, msg_id: str):
        info = self._msg_tags.get(msg_id)
        if not info:
            return

        # Put original text in input for editing.
        self._input.delete("1.0", tk.END)
        self._input.insert("1.0", info["text"])
        self._input.focus_set()

        # Temporarily rebind send to perform the edit.
        def _do_edit():
            new_text = self._input.get("1.0", tk.END).strip()
            if not new_text:
                return
            self._input.delete("1.0", tk.END)
            self.client.edit_message(msg_id, new_text)
            self._replace_message_text(msg_id, new_text)
            # Restore normal send binding.
            self._input.bind("<Return>", self._on_enter)

        self._input.bind("<Return>", lambda e: (_do_edit(), "break")[-1])

    def _replace_message_text(self, msg_id: str, new_text: str):
        tag = f"msg_{msg_id}"
        ranges = self._chat.tag_ranges(tag)
        if not ranges:
            return
        start, end = str(ranges[0]), str(ranges[-1])
        self._chat.configure(state=tk.NORMAL)
        self._chat.delete(start, end)

        info = self._msg_tags.get(msg_id, {})
        own = info.get("own", True)
        ts = datetime.now().strftime("%H:%M")
        label = "You" if own else "Peer"
        label_tag = "you_label" if own else "peer_label"
        bg_tag = "sent_bg" if own else "peer_bg"

        self._chat.insert(start, f"[{ts}] ", ("timestamp", tag, bg_tag))
        self._chat.insert(f"{start} lineend", f"{label}: ", (label_tag, tag, bg_tag))
        # Insert after the label
        self._chat.insert(f"{start} lineend", f"{new_text} (edited)\n", (tag, bg_tag))
        self._chat.configure(state=tk.DISABLED)

        if msg_id in self._msg_tags:
            self._msg_tags[msg_id]["text"] = new_text

    def _mark_deleted(self, msg_id: str):
        tag = f"msg_{msg_id}"
        ranges = self._chat.tag_ranges(tag)
        if not ranges:
            return
        start, end = str(ranges[0]), str(ranges[-1])
        self._chat.configure(state=tk.NORMAL)
        self._chat.delete(start, end)
        self._chat.insert(start, "[message deleted]\n", ("system", "deleted"))
        self._chat.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Client callbacks (called from background thread)
    # ------------------------------------------------------------------
    def _cb_new_message(self, msg_id, text, timestamp, sender=None):
        self.root.after(0, lambda: self._append_message(
            msg_id, text, timestamp, own=False))

    def _cb_edit(self, msg_id, new_text):
        self.root.after(0, lambda: self._replace_message_text(msg_id, new_text))

    def _cb_delete(self, msg_id):
        self.root.after(0, lambda: self._mark_deleted(msg_id))

    def _cb_peer_event(self, event_type):
        if event_type == "connected":
            self.root.after(0, lambda: self._append_system("Peer connected"))
            self.root.after(0, lambda: self._status_canvas.itemconfig(
                self._status_dot, fill=GREEN))
        elif event_type in ("disconnected", "disconnected_self"):
            self.root.after(0, lambda: self._append_system("Peer disconnected"))
            self.root.after(0, lambda: self._status_canvas.itemconfig(
                self._status_dot, fill=RED))
