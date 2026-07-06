#!/bin/bash
# Ghost Sender Setup — run this once on your friend's Mac
echo "Installing Ghost Sender dependencies..."
pip3 install python-socketio[client] cryptography
echo ""
echo "Done! Run the sender with:"
echo "  python3 app.py"
