#!/usr/bin/env python3
"""Ghost Sender — Send answers to the receiver's Ghost window."""

import argparse
import os
import sys
import tkinter as tk

# Ensure ghost package is importable regardless of how the script is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sender.client import ChatClient
from sender.ui import SenderUI


def main():
    parser = argparse.ArgumentParser(description="Ghost Sender")
    parser.add_argument(
        "--server",
        default="https://ghost-relay-4mvn.onrender.com",
        help="Socket.IO server URL",
    )
    args = parser.parse_args()

    root = tk.Tk()
    root.title("Ghost Sender")
    root.geometry("500x700")
    root.configure(bg="#1e1e1e")
    root.minsize(400, 500)

    client = ChatClient(server_url=args.server)
    _ui = SenderUI(root, client)

    client.connect()

    def _on_close():
        client.disconnect()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
