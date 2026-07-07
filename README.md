# Ghost

A private, on-device macOS assistant that listens to a live conversation, transcribes
both voices locally, and streams AI answers into a floating overlay. Speech-to-text runs
fully on-device (Parakeet / Apple Speech); only the AI answers use the Claude API.

---

## Requirements

- **Apple Silicon Mac** (M1/M2/M3/M4) — Intel Macs won't work (the STT models need Apple Silicon).
- **macOS 13+** (newer is better).
- **Python 3.12**
- **Homebrew** + **BlackHole 2ch** (virtual audio device, for capturing the other side's audio).
- An **Anthropic API key** — https://console.anthropic.com
- **~3 GB free disk** (dependencies + speech models).
- Internet: one-time to download models (~1.2 GB) and for the Claude API while running.

---

## Install (fresh Mac)

```bash
# 1. System tools
brew install python@3.12 blackhole-2ch

# 2. Get the code
gh repo clone pavansaipendry/ghost Ghost      # or: git clone <repo-url> Ghost
cd Ghost

# 3. Python environment (do NOT copy an old venv — always rebuild it here)
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements-full.txt

# 4. Your API keys (each machine keeps its own — never committed)
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
# optional — only if you run with --deepgram (cloud STT):
echo "DEEPGRAM_API_KEY=..." >> .env

# 5. Run (first launch downloads the on-device speech models — needs internet, ~1-2 min)
./run_ghost.sh --parakeet        # on-device, no extra key — the zero-setup default
# or, for faster cloud STT (needs the DEEPGRAM_API_KEY from step 4):
# ./run_ghost.sh --deepgram
```

### Grant permissions
On first launch macOS will ask for these — grant all four in
**System Settings → Privacy & Security**, then restart Ghost once:

- Screen Recording
- Microphone
- Accessibility (for the global hotkeys)
- Speech Recognition

---

## Run

```bash
./run_ghost.sh --parakeet
```

- `--parakeet` uses the on-device Parakeet engine for both voices (recommended, fully local).
- `--deepgram` uses **Deepgram (cloud)** streaming STT instead — much faster end-of-speech
  detection (~0.5s vs ~2s) and strong tech-term accuracy, but it streams your call audio to
  Deepgram's servers (NOT on-device) and needs `DEEPGRAM_API_KEY` in `.env`
  (get one at console.deepgram.com). Both voices go through Deepgram in this mode.
- Leave both off to use the Apple Speech engine.

Answers route by difficulty for speed: quick/behavioral → Haiku (~0.5s to first word),
typical → Sonnet, hard design/coding → Opus.

Use **headphones** so your mic doesn't echo the other side. On speakers, add
`--interviewer-only`.

---

## Hotkeys

| Shortcut | Action |
|---|---|
| Hold **Ctrl** | Make the overlay clickable (release = click-through again) |
| **Ctrl + a** | Focus the "Ask the LLM" box — type a question, Enter to send |
| **Ctrl + 0** | AI view |
| **Double-tap Right-Option** | Answer the current question now |
| **Double-tap Right-Shift** | Answer what's on the screen (vision) |
| **Double-tap Right-Command** | Toggle the floating screen box |
| **Ctrl + ↑ ↓ ← →** | Move the overlay window |
| **Ctrl + `[` / `]`** | Window taller / shorter |
| **Ctrl + `,` / `.`** (`<` / `>`) | Window wider / narrower |
| **Ctrl + `-` / `=`** | Volume down / up (works even while the Ghost Audio device is active) |
| **Ctrl + 9** | Kill switch |

These window/volume hotkeys are suppressed at the system level, so they make no beep and
don't trigger macOS Mission Control / Spaces.

---

## Menu-bar app — launch without the terminal (optional, not yet enabled)

A 👻 menu-bar controller (`ghost/ai/controller.py`) and a double-click `Ghost.app`
are built and working. They let you Start/Stop Ghost from the menu bar instead of
a terminal. **They're not active yet** because this repo lives under `~/Desktop`,
which macOS privacy-protects — a Finder-launched app can't read the venv there and
dies with `Operation not permitted`. To enable it later, do **one** of:

- **Grant Full Disk Access to `Ghost.app`** (System Settings → Privacy & Security →
  Full Disk Access), then double-click `Ghost.app`. Ad-hoc code-sign it first so the
  grant sticks: `codesign --force --deep -s - Ghost.app`.
- **Move the repo out of `~/Desktop`** (e.g. `~/ghost`) — no permission needed.

Until then, keep launching from the terminal with `./run_ghost.sh --parakeet`.
Startup problems with the menu-bar app are logged to `logs/launcher.log`.

Manual run of the controller (from a terminal that already has Desktop access):
`venv/bin/python -m ghost.ai.controller`.

## Keeping two Macs in sync

The code lives in a private git repo. To push a fix and pull it on the other Mac:

```bash
# On the Mac where you fixed something:
git add -A && git commit -m "fix: ..." && git push

# On the other Mac, before using it:
git pull
pip install -r requirements-full.txt   # only if dependencies changed
```

`.env` (your key), `sessions/` (recordings), and `venv/` never sync — they stay local
to each machine by design.

---

## Troubleshooting

- **No transcript / "THEM" meter dead** → audio isn't reaching Ghost. It's a routing
  issue, not the app: make sure BlackHole is installed and the system output is routed to
  "Ghost Audio" (Ghost tries to set this up automatically; the watchdog re-fixes it if
  AirPods reconnect).
- **"Speech Recognition not authorized"** → grant it in System Settings → Privacy &
  Security → Speech Recognition, then relaunch.
- **First launch is slow** → it's downloading the speech models (one-time). Needs internet.
- **`pip install` fails** → confirm you're on Python 3.12 and Apple Silicon (`python3.12 --version`, `uname -m` → `arm64`).
