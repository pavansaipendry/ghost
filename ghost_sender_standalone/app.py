#!/usr/bin/env python3
"""Ghost Sender — Send answers to the receiver's Ghost window.

Setup (one time):
    pip install python-socketio[client] cryptography

Run:
    python app.py
"""

import tkinter as tk
from client import ChatClient
from ui import SenderUI

SERVER = "https://ghost-relay-4mvn.onrender.com"


def main():
    root = tk.Tk()
    root.title("Ghost Sender")
    root.geometry("500x700")
    root.configure(bg="#1e1e1e")
    root.minsize(400, 500)

    client = ChatClient(server_url=SERVER)
    _ui = SenderUI(root, client)

    client.connect()

    def _on_close():
        client.disconnect()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
