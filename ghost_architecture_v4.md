# GHOST
## Stealth Document Viewer

**Architecture & Technical Specification**
v5.0 | March 2026
Personal use only. Not for distribution.

---

## 1. Overview

Ghost is a stealth document viewer for macOS. You load up to 7 documents before a meeting, then during the call you press Ctrl+number (1-7) to instantly open any document in a translucent window. You scroll through it, find what you need, and answer the question out loud. The window has a low-opacity background so it blends into your screen, but the text stays crisp and readable. Most importantly, the window is completely invisible to other meeting participants -- even if you share your screen.

No AI. No API calls. No audio capture. No transcription. No internet required during the meeting. Just your documents, always at your fingertips, invisible to everyone else.

---

## 2. How It Works

1. Before the meeting: launch Ghost and load up to 7 documents (PDF, DOCX, MD, TXT)
2. Ghost shows a numbered list of your documents (1-7) in a small translucent window
3. Join your meeting on Zoom, Google Meet, or Microsoft Teams as normal
4. Someone asks you a question -- you press Ctrl+number to open the relevant document
5. The document renders in the Ghost window. You scroll through it and find the answer.
6. You answer the question out loud.
7. Press Ctrl+another number to switch documents, or press Ctrl+0 / Escape to go back to the document list.

That is the entire workflow. No typing, no searching, no waiting. Just Ctrl+number and scrolling.

---

## 3. Design Principles

- **Dead simple:** Ctrl+number to switch docs, scroll to find answers, nothing else
- **Invisible to screenshare:** macOS sharingType = .none ensures the window never appears in screen capture
- **Translucent background, crisp text:** low-opacity dark background so you can see your meeting behind it, but document text stays fully readable at 100% opacity
- **Zero cost:** no API calls, no subscriptions, no internet needed during the meeting
- **Zero latency:** documents are loaded in memory, switching is instant
- **Minimal footprint:** no dock icon, no app switcher entry, just a floating window and a tray icon

---

## 4. Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.11+ | Application logic |
| Window | PyObjC (NSPanel) | Native macOS stealth window with sharingType = .none |
| Background | NSVisualEffectView | Translucent dark blur effect |
| Document Renderer | WKWebView (via PyObjC) | Renders document content in a scrollable web view, embedded directly in the NSPanel |
| PDF Parsing | PyMuPDF (fitz) | Renders PDF pages as images, extracts text for search overlay |
| DOCX Parsing | python-docx | Extracts text and structure from Word documents |
| MD Rendering | markdown + pygments | Converts Markdown to styled HTML |
| Keyboard Listener | pynput | Global Ctrl+number key listener for document switching |
| System Tray | NSStatusBar (via PyObjC) | Menu bar icon for loading docs and settings |
| Config | TOML | User preferences (opacity, position, size, font size) |

Total dependency footprint: under 60MB. No ML models, no audio libraries, no API SDKs. Lean and fast.

**Why pure PyObjC instead of pywebview + rumps:** pywebview creates its own NSWindow internally and cannot be embedded inside a custom NSPanel. rumps runs its own NSApplication event loop, conflicting with the PyObjC run loop. By using WKWebView and NSStatusBar directly via PyObjC, everything runs on a single NSApplication run loop. One process, one event loop, zero conflicts. pynput runs on its own background thread and stays out of the way.

---

## 5. System Architecture

Ghost is a single Python process with three components: a native window, a web view renderer, and a keyboard listener. That is it.

### 5.1 Components

| Component | Responsibility |
|-----------|---------------|
| Window Manager | Creates and manages the NSPanel with sharingType = .none, NSVisualEffectView background, floating level, position/size persistence |
| Document Renderer | Parses documents into styled HTML, renders them in WKWebView inside the NSPanel. Handles scrolling, font sizing, and navigation. |
| Input Handler | Listens for global key presses (Ctrl+1-7 to open docs, Ctrl+0/Escape for doc list, +/- for font size, Cmd+Shift+Q to quit) |
| Document Loader | Parses DOCX, MD, TXT into HTML. Renders PDF pages as images with optional text overlay for search. |
| Tray Menu | NSStatusBar menu bar icon with options: Load Documents, Settings, About, Quit |

### 5.2 Data Flow

| Step | What Happens |
|------|-------------|
| 1 | User loads documents via tray menu or drag-and-drop. Documents are parsed into HTML and stored in memory. |
| 2 | Ghost displays a numbered document list in the window (e.g., "1. Q3 Report.pdf  2. Project Plan.docx") |
| 3 | User presses Ctrl+number (e.g., Ctrl+3) |
| 4 | Window Manager tells Document Renderer to display document #3 |
| 5 | Document Renderer loads the pre-parsed HTML into the web view. Instant -- no parsing delay. |
| 6 | User scrolls through the document, reads what they need |
| 7 | User presses 0 or Escape to return to the document list, or another number to switch directly |

---

## 6. Stealth Mechanism

### 6.1 sharingType = .none

The Ghost window is an NSPanel with sharingType set to .none. This is the official Apple API (macOS 12 Monterey and later) that excludes a window from all screen capture APIs. Every major meeting app -- Zoom, Google Meet, Microsoft Teams -- uses Apple ScreenCaptureKit or CGWindowList for screen sharing, both of which respect this property.

The window is fully visible on your physical display. You can see it, scroll it, interact with it. But in any screen share or screen recording, it simply does not exist. This is not a hack -- it is the intended Apple mechanism for privacy-sensitive windows.

### 6.2 Window Properties

| Property | Value | Effect |
|----------|-------|--------|
| Type | NSPanel | Utility window -- no dock icon, no Cmd+Tab |
| sharingType | .none | Invisible to all screen capture |
| Level | NSFloatingWindowLevel | Floats above meeting app window |
| Background | NSVisualEffectView (.dark material) | Translucent dark blur |
| Background Alpha | ~0.3 to 0.5 (configurable) | Low opacity -- you see through to your meeting |
| Text Opacity | 1.0 (full) | Text is always crisp and fully readable |
| LSUIElement | true | No dock icon, no app switcher |
| Default Size | 500x700px, resizable | Big enough to read comfortably |
| Position | Draggable, persisted across sessions | Put it wherever works for you |

### 6.3 The Translucency Effect

The key visual trick: the window background is translucent (you can see your meeting app behind it), but the text rendered inside is fully opaque. This is achieved by layering:

- **Layer 1 (bottom):** NSVisualEffectView with .dark material and reduced alpha (0.3-0.5). This creates the see-through dark glass effect.
- **Layer 2 (top):** WKWebView rendering HTML content with a transparent background (background: transparent in CSS). The text itself has color: white with full opacity.

Result: the background blends into whatever is behind it (your meeting window), but the document text pops with full contrast. You can read comfortably without the window feeling like it is blocking your view.

### 6.4 macOS 11 and Below

sharingType requires macOS 12+. On older systems, the fallback is to place Ghost on a secondary monitor and share only the primary. Ghost detects the OS version at startup and warns if the stealth API is unavailable.

---

## 7. Window UI Design

### 7.1 Document List View (Home)

When Ghost starts or when you press 0/Escape, it shows the document list:

- **Title bar:** "GHOST" label + minimize button
- **Document list:** numbered 1-7, each showing the filename and file type icon
  - Example: "1  Q3 Financial Report.pdf"
  - Example: "2  Project Timeline.docx"
  - Example: "3  Meeting Notes.md"
- Empty slots show as dimmed (e.g., "4  --" if only 3 docs loaded)
- **Bottom:** "Press Ctrl+1-7 to open | Drop files to load" hint text

### 7.2 Document View

When you press a number key, the document fills the window:

- **Top bar:** document name + back arrow (or press 0/Escape) + font size controls (+/-)
- **Main area:** full scrollable document content
  - PDF: rendered page by page as images (via PyMuPDF get_pixmap), with optional text overlay for search
  - DOCX: headings, paragraphs, tables, lists rendered as styled HTML
  - Markdown: fully rendered with syntax highlighting for code blocks
  - Plain text: monospace, preserving whitespace
- Scroll bar on the right edge for navigation
- **Cmd+F:** in-document text search (handled by the web view natively)

### 7.3 Visual Style

- **Background:** dark translucent glass (alpha 0.3-0.5, configurable)
- **Document text:** white, 14-16px (adjustable with +/- keys), full opacity
- **Headings:** slightly larger, bold, light blue accent (#8AB4F8)
- **Tables:** subtle borders, alternating row shading at low opacity
- **Code blocks:** slightly lighter background, monospace font
- **Links:** light blue, underlined
- **Images from PDFs/DOCX:** rendered inline at appropriate size
- No animations, no transitions. Instant switching between docs.

---

## 8. Document Parsing

Each document type is parsed into styled HTML at load time. During the meeting, switching documents just swaps the pre-rendered HTML in the web view -- zero parsing delay.

### 8.1 PDF

- **Renderer:** PyMuPDF (fitz)
- Each page is rendered as an image using page.get_pixmap() and embedded as base64 data URIs in the HTML
- This avoids the fragile and complex problem of converting PDF layout (tables, columns, forms) into HTML
- Page breaks are preserved as visual dividers between page images
- Text is extracted separately via page.get_text() for a hidden search overlay (enables Cmd+F)
- Scanned/image-only PDFs render identically (just no searchable text layer)
- **Future optimization:** selective text-based rendering for simple PDFs (Phase 2+)

### 8.2 DOCX

- **Parser:** python-docx
- Headings mapped to HTML h1-h6 tags
- Paragraphs to p tags with formatting (bold, italic, underline preserved)
- Tables rendered as HTML tables with cell formatting
- Lists rendered as ul/ol with proper nesting
- Images extracted and embedded as base64

### 8.3 Markdown

- **Parser:** Python markdown library with extensions (tables, fenced code, toc)
- Code blocks syntax-highlighted with Pygments
- Rendered as standard styled HTML

### 8.4 Plain Text

- Loaded as-is, wrapped in a pre tag with monospace font
- Line numbers optionally shown on the left margin

---

## 9. Keyboard Controls

| Key | Context | Action |
|-----|---------|--------|
| Ctrl + 1-7 | Any time (global) | Open document #1 through #7 |
| Ctrl + 0 or Escape | In document view | Back to document list |
| + or = | In document view (focused) | Increase font size |
| - (minus) | In document view (focused) | Decrease font size |
| Cmd + F | In document view (focused) | Search within the current document |
| Cmd + Shift + O | Any time | Open file picker to load documents |
| Cmd + Shift + Q | Any time | Quit Ghost |
| Scroll / Trackpad | In document view | Scroll through the document |

**Modifier-based global keys:** Document switching uses Ctrl+number instead of bare number keys. This eliminates the need for a toggle/listening mode -- you can type "Q1 results" in meeting chat without Ghost intercepting the "1". The Ctrl modifier is unlikely to conflict with meeting app shortcuts. Plain number keys always pass through to the focused app.

Other shortcuts (+/-, Cmd+F) require the Ghost window to be focused and do not need a modifier since they only fire when Ghost is the active window.

---

## 10. Project Structure

```
ghost/
  main.py                    -- entry point, initializes NSApplication, window, tray, key listener
  window/panel.py            -- PyObjC NSPanel setup (sharingType, vibrancy, floating level)
  window/webview.py          -- WKWebView setup via PyObjC, loads HTML strings, handles doc switching
  documents/loader.py        -- dispatcher: routes files to the correct parser
  documents/pdf_parser.py    -- PyMuPDF: PDF pages to images + text extraction for search
  documents/docx_parser.py   -- python-docx: DOCX to HTML conversion
  documents/md_parser.py     -- markdown + pygments: MD to HTML
  documents/txt_parser.py    -- plain text to HTML (pre tag)
  input/keys.py              -- pynput global key listener (Ctrl+1-7 for docs, hotkeys)
  ui/tray.py                 -- NSStatusBar menu bar icon and menu (via PyObjC)
  ui/web/index.html          -- document list view template
  ui/web/viewer.html         -- document rendering view template
  ui/web/style.css           -- dark translucent theme, typography, doc styles
  ui/web/app.js              -- doc switching, scroll, font size, search
  config/settings.toml       -- opacity, font size, window position/size
  tests/                     -- unit tests for parsers, integration tests for window
```

---

## 11. Dependencies

| Package | Version | Size | Purpose |
|---------|---------|------|---------|
| pyobjc-framework-Cocoa | >=10.0 | ~15MB | NSPanel, NSVisualEffectView, NSStatusBar, NSApplication |
| pyobjc-framework-WebKit | >=10.0 | ~2MB | WKWebView for document rendering |
| PyMuPDF (fitz) | >=1.24 | ~30MB | PDF page-to-image rendering and text extraction |
| python-docx | >=1.1 | ~5MB | DOCX parsing |
| markdown | >=3.6 | ~1MB | Markdown to HTML conversion |
| pygments | >=2.18 | ~10MB | Syntax highlighting for code blocks |
| pynput | >=1.7 | ~2MB | Global keyboard listener (Ctrl+number) |
| toml | >=0.10 | <1MB | Config file parsing |

Total: 6 packages, under 65MB installed. No ML models, no audio libraries, no API SDKs, no internet required during use. Ghost runs entirely offline once documents are loaded.

**Removed:** pywebview (cannot embed in custom NSPanel), rumps (event loop conflict with PyObjC). Both replaced by direct PyObjC equivalents (WKWebView, NSStatusBar) that run on the same NSApplication run loop.

External: None. No additional software to install.

---

## 12. Build Phases

### Phase 1: Stealth Window + Text Docs (3-4 days)

- Project scaffolding, venv, config
- PyObjC NSPanel with sharingType = .none and NSVisualEffectView
- WKWebView embedded directly inside the NSPanel via PyObjC
- NSStatusBar tray icon (Load Documents, Quit)
- Load plain text and Markdown files, render as HTML in the WKWebView
- Ctrl+number key switching (Ctrl+1-7) via pynput on background thread
- Document list home screen
- Verify stealth: confirm window is invisible in Zoom, Meet, and Teams screenshare

### Phase 2: PDF + DOCX Support (3-4 days)

- PDF renderer: PyMuPDF page.get_pixmap() to render pages as images
- PDF text extraction: page.get_text() for hidden search overlay (enables Cmd+F on PDFs)
- DOCX parser: python-docx with full formatting preservation
- Styled HTML rendering for DOCX
- In-document search (Cmd+F via WKWebView)
- Font size adjustment (+/- keys)
- Scroll position remembered per document

### Phase 3: Polish (2-3 days)

- Tray menu enhancements (settings, about)
- Drag-and-drop document loading onto the window
- Window position/size persistence across sessions
- Configurable background opacity via settings or keyboard shortcut
- Error handling (corrupt files, unsupported formats, too many documents)

### Phase 4: Packaging (3-4 days)

- Package as standalone .app with py2app
- App icon and branding
- First-launch permission prompts (Accessibility for pynput)
- Code signing and notarization for macOS Gatekeeper
- Testing WKWebView and Accessibility entitlements in the .app bundle
- README with setup instructions

---

## 13. Security & Privacy

- Ghost runs entirely offline during meetings. No network calls whatsoever.
- Documents stay local in memory. Nothing is uploaded, synced, or cached to disk beyond the original files.
- No API keys. No accounts. No telemetry. No analytics.
- The Ghost window cannot be captured by any screen recording or sharing tool on macOS 12+.
- pynput requires Accessibility permission (System Settings > Privacy > Accessibility). This is a one-time macOS prompt.
- When Ghost quits, all parsed document data is freed from memory. Nothing persists.

---

## 14. Known Limitations

| Limitation | Details | Workaround |
|-----------|---------|------------|
| macOS only | sharingType = .none is an Apple API. No Windows/Linux equivalent. | None. This is macOS-specific by design. |
| macOS 12+ required for stealth | sharingType not available on macOS 11 and below | Use a secondary monitor and share only primary display. |
| Max 7 documents | Limited to single-digit number keys for quick access | Swap documents via tray menu if you need more than 7. |
| Scanned PDFs | Image-only PDFs have no extractable text | Ghost renders pages as images. No text search available. |
| Ctrl+number conflict | Ctrl+1-7 captured globally; may conflict with rare app shortcuts | Unlikely in practice -- few apps use Ctrl+number on macOS. |
| PDF text search | PDFs rendered as images; text search depends on extractable text layer | Scanned/image-only PDFs won't have searchable text. |

---

## 15. Cost

Zero. Ghost is free to run. There are no API calls, no subscriptions, no cloud services. The only cost is your time building it.

---

## 16. Future Ideas

- **AI Q&A mode (optional):** toggle on Claude API integration for document Q&A alongside manual browsing
- **Bookmarks:** mark important sections in documents for quick jump during meetings
- **Annotations:** highlight or underline text within Ghost for emphasis
- **Multi-window:** open multiple documents side by side in separate stealth panels
- **Quick notes:** a scratchpad area in the window for jotting things down during the meeting
- **Document tabs:** horizontal tabs instead of number keys for more than 7 documents
- **Auto-load from folder:** point Ghost at a folder and it loads all supported files
- **Export highlights:** save any text you highlighted during the meeting to a summary file
