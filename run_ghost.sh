#!/bin/bash
# Ghost AI — one-command launcher for a Meet/Zoom call (works on AirPods).
#
# Captures the OTHER person's voice via BlackHole, auto-creates the "Ghost Audio"
# device AND auto-switches your output to it (restored on quit). Reads your key
# from .env. Loads the active role context from ./contexts/ml_engineer (your resume).
#
# DEFAULT = BOTH voices, dual-engine STT:
#   • Interviewer (BlackHole call feed) → Apple on-device streaming STT — drives answers.
#   • You (mic)                         → mlx-whisper, running in PARALLEL — context only.
# Two separate engines, so both people are transcribed at the same time and the
# interviewer can NEVER be mislabeled as you (the user-voice path drops any audio
# that arrives while the interviewer is speaking — see ghost/ai/user_voice.py).
#
# Usage:   ./run_ghost.sh                      (BlackHole, BOTH voices — recommended)
#          ./run_ghost.sh --interviewer-only   (mic OFF — only the interviewer is
#                                                transcribed; use if you don't want
#                                                your own voice captured at all)
#          ./run_ghost.sh --mic                (override: use the microphone as the
#                                                single source instead of BlackHole)
#
# In the app:  Ctrl+0 = AI view   •   Double-tap Right-Option = answer now   •   Ctrl+Shift+Q = quit
cd "$(dirname "$0")"

MODE="--blackhole"
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --mic|--app)  MODE="" ;;              # single-source modes: no BlackHole
    --track-me)   continue ;;             # legacy no-op (tracking both is now the default)
  esac
  ARGS+=("$arg")
done

exec venv/bin/python -m ghost.ai.entry $MODE --context ./contexts/ml_engineer "${ARGS[@]}"
