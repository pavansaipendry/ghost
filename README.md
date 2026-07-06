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

# 4. Your API key (each machine keeps its own — never committed)
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 5. Run (first launch downloads the speech models — needs internet, ~1-2 min)
./run_ghost.sh --parakeet
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

- `--parakeet` uses the on-device Parakeet engine for both voices (recommended).
- Leave it off to use the Apple Speech engine instead.

Use **headphones** so your mic doesn't echo the other side. On speakers, add
`--interviewer-only`.

---

## Hotkeys

| Shortcut | Action |
|---|---|
| Hold **Ctrl** | Make the overlay clickable (release = click-through again) |
| **Ctrl + a** | Focus the "Ask the LLM" box — type a question, Enter to send |
| **Ctrl + 0** | AI view |
| **Ctrl + 1–7** | Document slots |
| **Double-tap Right-Option** | Answer the current question now |
| **Double-tap Right-Shift** | Answer what's on the screen (vision) |
| **Double-tap Right-Command** | Toggle the floating screen box |
| **Ctrl + 9** | Kill switch |

---

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
