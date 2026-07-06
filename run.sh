#!/bin/bash
# Run Ghost with optional document files as arguments
# Usage: ./run.sh [file1.pdf] [file2.md] [file3.txt] ...
cd "$(dirname "$0")"
source venv/bin/activate
python3 -m ghost.main "$@"
