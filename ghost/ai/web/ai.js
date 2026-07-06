// Ghost AI View — chat-style conversation log.
// Three message types: interviewer (their questions), you (your speech),
// ai (Ghost's streamed answer). Live in-progress lines show at the bottom.

const GhostAI = {
    status: 'idle',
    messages: [],            // committed: [{speaker:'interviewer'|'you'|'ai', text}]
    live: { interviewer: '', you: '' },  // in-progress transcript per speaker
    ai: null,                // {text, streaming} current AI answer, or null
    screen: '',              // latest OCR'd screen text (live, not saved to history)
    banner: null,            // {message, kind} blocking routing banner, or null
    meters: {                // per-source audio meters (them vs you)
        interviewer: { level: 0, on: false, enabled: true },
        you: { level: 0, on: false, enabled: false },
    },
    darkText: false,         // Ctrl+B: dark text for white backgrounds behind Ghost

    init() { this.render(); },

    render() {
        document.body.innerHTML = `
            <div class="ghost-drag-handle">GHOST AI</div>
            <div class="ai-container">
                <div class="ai-banner-slot" id="ai-banner-slot">${this._renderBanner()}</div>
                <div class="ai-status-bar">
                    <div class="ai-status-dot ${this.status}" id="ai-status-dot"></div>
                    <span class="ai-status-text" id="ai-status-text">${this._statusText()}</span>
                    <div class="ai-meters" id="ai-meters">${this._renderMeters()}</div>
                </div>
                <div class="ai-chat" id="ai-chat">${this._renderChat()}</div>
                <div class="ai-ask">
                    <textarea id="ai-ask-input" class="ai-ask-input" rows="1"
                        placeholder="Ask the LLM…  (hold Ctrl to click, Enter to send)"></textarea>
                </div>
            </div>`;
        this._wireAsk();
        this._scroll();
        document.body.classList.toggle('dark-text', this.darkText);  // survive re-renders
    },

    // Two live level meters — "THEM" (interviewer / BlackHole) and "YOU" (mic).
    // Separate bars make routing failures diagnosable at a glance: if THEM is dead
    // while the interviewer is talking, the call audio isn't reaching Ghost.
    _renderMeters() {
        const bar = (key, label) => {
            const m = this.meters[key];
            if (!m.enabled) return '';
            const pct = Math.min(100, Math.round(m.level * 600));  // ~0.166 rms → full
            const cls = m.on ? 'on' : 'off';
            return `<div class="ai-meter ai-meter-${key} ${cls}" title="${label} audio level">
                <span class="ai-meter-label">${label}</span>
                <span class="ai-meter-track"><span class="ai-meter-fill" style="width:${pct}%"></span></span>
            </div>`;
        };
        return bar('interviewer', 'THEM') + bar('you', 'YOU');
    },

    _renderBanner() {
        if (!this.banner) return '';
        const kind = this.banner.kind || 'error';
        return `<div class="ai-banner ai-banner-${kind}">
            <span class="ai-banner-icon">${kind === 'ok' ? '✅' : '⛔'}</span>
            <span class="ai-banner-text">${this.escapeHtml(this.banner.message)}</span>
        </div>`;
    },

    // Wire the "Ask the LLM" input → posts the question to Python (brain.ask).
    // Focused via Ctrl+A (GhostAI.focusAsk) or by holding Ctrl and clicking.
    _wireAsk() {
        const input = document.getElementById('ai-ask-input');
        if (!input) return;
        const post = (msg) => {
            try { window.webkit.messageHandlers.ghost.postMessage(msg); } catch (e) { /* bridge not ready */ }
        };
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const text = input.value.trim();
                if (text) post({ action: 'ask', text });
                input.value = '';
                input.blur();          // hand the keyboard back to the interview app
            } else if (e.key === 'Escape') {
                e.preventDefault();
                input.value = '';
                input.blur();
            }
        });
        // When the box loses focus (sent / escaped / clicked away), tell Python to
        // restore click-through so the cursor + keys go back to the interview app.
        input.addEventListener('blur', () => post({ action: 'ask_blur' }));
    },

    // Ctrl+A entry point: focus the ask box so the user can type immediately.
    focusAsk() {
        const input = document.getElementById('ai-ask-input');
        if (input) { input.focus(); input.select(); }
    },

    // Ctrl+B: flip the readable text between light (default) and near-black, so it
    // stays visible when the screen behind Ghost is white.
    toggleTextColor() {
        this.darkText = !this.darkText;
        document.body.classList.toggle('dark-text', this.darkText);
    },

    _renderChat() {
        let html = '';
        if (this.messages.length === 0 && !this.ai && !this.live.interviewer && !this.live.you) {
            html += `<div class="ai-empty"><div class="ai-logo">GHOST AI</div>Listening…</div>`;
        }
        for (const m of this.messages) html += this._bubble(m.speaker, m.text, false);
        // live in-progress lines (greyed, with cursor)
        if (this.live.interviewer) html += this._bubble('interviewer', this.live.interviewer, true);
        if (this.live.you) html += this._bubble('you', this.live.you, true);
        // streaming AI answer
        if (this.ai) html += this._bubble('ai', this.ai.text, this.ai.streaming);
        return html;
    },

    _bubble(speaker, text, live) {
        const label = { interviewer: 'INTERVIEWER', you: 'YOU', ai: 'GHOST AI' }[speaker] || speaker;
        const cursor = live ? '<span class="ai-cursor"></span>' : '';
        // Ghost AI answers render as markdown (bold, code blocks, lists);
        // interviewer / you stay plain text.
        const body = (speaker === 'ai') ? this._md(text) : this.escapeHtml(text);
        return `<div class="msg msg-${speaker}${live ? ' msg-live' : ''}">
            <div class="msg-label">${label}</div>
            <div class="msg-text">${body}${cursor}</div>
        </div>`;
    },

    // Minimal, offline markdown → HTML for AI answers. Handles fenced code blocks
    // (```lang ... ```, incl. an unterminated one mid-stream), inline `code`,
    // **bold**, *italic* / _italic_, headings, and -/*/1. lists. Everything is
    // HTML-escaped first, so it's safe to render.
    _md(src) {
        if (!src) return '';
        const esc = (s) => this.escapeHtml(s);
        const blocks = [];
        // Pull out closed fenced code blocks, then any unterminated trailing fence.
        let text = src.replace(/```([^\n`]*)\n([\s\S]*?)```/g, (m, lang, code) => {
            blocks.push({ lang: (lang || '').trim(), code });
            return `\n@@CODE${blocks.length - 1}@@\n`;
        });
        text = text.replace(/```([^\n`]*)\n?([\s\S]*)$/, (m, lang, code) => {
            blocks.push({ lang: (lang || '').trim(), code });
            return `\n@@CODE${blocks.length - 1}@@\n`;
        });

        const inline = (s) => esc(s)
            .replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>')
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/\b_([^_\n]+)_\b/g, '<em>$1</em>')
            .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');

        const lines = text.split('\n');
        let html = '', list = null;
        const closeList = () => { if (list) { html += `</${list}>`; list = null; } };

        for (const raw of lines) {
            const line = raw.replace(/\s+$/, '');
            let m;
            if (m = line.match(/^@@CODE(\d+)@@$/)) {
                closeList();
                const b = blocks[+m[1]];
                const lbl = b.lang ? `<div class="md-code-lang">${esc(b.lang)}</div>` : '';
                const code = esc(b.code.replace(/\n$/, ''));
                html += `<div class="md-code">${lbl}<pre><code>${code}</code></pre></div>`;
            } else if (line.trim() === '') {
                closeList();
            } else if (m = line.match(/^(#{1,4})\s+(.*)$/)) {
                closeList();
                html += `<div class="md-h md-h${m[1].length}">${inline(m[2])}</div>`;
            } else if (m = line.match(/^\s*[-*]\s+(.*)$/)) {
                if (list !== 'ul') { closeList(); html += '<ul>'; list = 'ul'; }
                html += `<li>${inline(m[1])}</li>`;
            } else if (m = line.match(/^\s*\d+\.\s+(.*)$/)) {
                if (list !== 'ol') { closeList(); html += '<ol>'; list = 'ol'; }
                html += `<li>${inline(m[1])}</li>`;
            } else {
                closeList();
                html += `<div class="md-p">${inline(line)}</div>`;
            }
        }
        closeList();
        return html;
    },

    // ── Called from Python ──

    // Replay the full saved conversation (survives view switches / reloads).
    loadHistory(arr) {
        this.messages = Array.isArray(arr) ? arr : [];
        this.live = { interviewer: '', you: '' };
        this.ai = null;
        this.render();
    },

    // Live (in-progress) transcript for a speaker — overwrites until committed.
    liveLine(speaker, text) {
        if (speaker !== 'interviewer' && speaker !== 'you') return;
        this.live[speaker] = text || '';
        this._renderChatOnly();
    },

    // Finalized line — appended to the chat. Consecutive utterances from the SAME
    // speaker merge into one bubble (turn-based); a new bubble starts only when the
    // speaker changes. So a pausing interviewer stays one box, not many small ones.
    commitLine(speaker, text) {
        if (!text) { this.live[speaker] = ''; this._renderChatOnly(); return; }
        const last = this.messages[this.messages.length - 1];
        if (last && last.speaker === speaker) {
            last.text = (last.text + ' ' + text).trim();
        } else {
            this.messages.push({ speaker, text });
        }
        this.live[speaker] = '';
        this._renderChatOnly();
    },

    aiStart() {
        this.ai = { text: '', streaming: true };
        this.status = 'answering';
        this.setStatus('answering');
        this._renderChatOnly();
    },

    aiToken(token) {
        if (!this.ai) this.ai = { text: '', streaming: true };
        this.ai.text += token;
        this._renderChatOnly();
    },

    aiDone() {
        if (this.ai) {
            this.messages.push({ speaker: 'ai', text: this.ai.text });
            this.ai = null;
        }
        this.setStatus('connected');
        this._renderChatOnly();
    },

    showError(message) {
        this.setStatus('error');
        this.messages.push({ speaker: 'ai', text: '⚠️ ' + message });
        this._renderChatOnly();
    },

    setStatus(status) {
        this.status = status;
        const dot = document.getElementById('ai-status-dot');
        const text = document.getElementById('ai-status-text');
        if (dot) dot.className = 'ai-status-dot ' + status;
        if (text) text.textContent = this._statusText();
    },

    setAudioLevel(connected, level) {
        // Don't clobber an in-progress answer or the vision "reading" indicator.
        if (this.status === 'answering' || this.status === 'vision') return;
        // A blocking routing banner owns the status line — don't flip it to green.
        if (this.banner && this.banner.kind !== 'ok') return;
        this.setStatus(connected ? 'connected' : 'waiting');
    },

    // Per-source level from the pipeline → update one meter in place (no full render).
    setSourceLevel(source, connected, level) {
        const m = this.meters[source];
        if (!m) return;
        m.enabled = true;
        m.level = level || 0;
        m.on = !!connected;
        this._refreshMeters();
    },

    _refreshMeters() {
        const el = document.getElementById('ai-meters');
        if (el) el.innerHTML = this._renderMeters();
    },

    // Blocking routing banner. kind: 'error' (red, capture is broken) or 'ok'
    // (green, transient "fixed" confirmation).
    showBanner(message, kind) {
        this.banner = { message: message || '', kind: kind || 'error' };
        this._refreshBanner();
        if (kind !== 'ok') this.setStatus('error');
    },

    hideBanner() {
        this.banner = null;
        this._refreshBanner();
    },

    _refreshBanner() {
        const el = document.getElementById('ai-banner-slot');
        if (el) el.innerHTML = this._renderBanner();
        else this.render();
    },

    // Screen OCR now lives in the separate floating SCREEN box, not the main chat.
    // Kept as a no-op so any stray call is harmless.
    setScreen(text) { /* moved to the floating screen box */ },

    clearAll() {
        this.status = 'idle';
        this.messages = [];
        this.live = { interviewer: '', you: '' };
        this.ai = null;
        this.screen = '';
        this.banner = null;
        this.meters.interviewer = { level: 0, on: false, enabled: false };
        this.meters.you = { level: 0, on: false, enabled: false };
        this.render();
    },

    // ── Helpers ──

    _renderChatOnly() {
        const el = document.getElementById('ai-chat');
        if (!el) { this.render(); return; }
        // The viewport is NEVER moved by incoming content. Streaming answers, live
        // transcript, and new bubbles all update in place at the user's exact scroll
        // offset — only the user's own scrolling changes what they're looking at.
        // (Previously this auto-stuck to the bottom, which yanked the view down as
        // answers streamed in — that's the behavior being removed.)
        const prevTop = el.scrollTop;
        el.innerHTML = this._renderChat();
        el.scrollTop = prevTop;
    },

    _scroll() {
        const el = document.getElementById('ai-chat');
        if (el) el.scrollTop = el.scrollHeight;
    },

    _statusText() {
        switch (this.status) {
            case 'idle': return 'Ready';
            case 'connected': return '🟢 Listening';
            case 'waiting': return 'Waiting for audio — check output device';
            case 'answering': return 'Ghost is answering…';
            case 'vision': return '📸 Reading the screen…';
            case 'error': return 'Error';
            default: return this.status;
        }
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

document.addEventListener('DOMContentLoaded', () => GhostAI.init());
