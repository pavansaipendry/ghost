// Ghost Live Chat UI Controller
// Communicates with Python via WKWebView message handlers

const GhostLive = {
    messages: [],       // [{id, text, timestamp, isOwn, edited}]
    autoScroll: true,   // track if user scrolled up
    roomCode: '',
    status: 'connecting',

    init() {
        this.render();
        this._setupScrollDetection();
    },

    render() {
        document.body.innerHTML = `
            <div class="ghost-drag-handle">GHOST LIVE</div>
            <div class="live-container">
                <div class="live-header">
                    <div class="live-room-info">
                        <span class="live-room-code">${this.roomCode ? 'Room: ' + this.escapeHtml(this.roomCode) : 'Live Chat'}</span>
                        <span class="live-status live-status-${this.status}">${this._statusText()}</span>
                    </div>
                </div>
                <div class="live-messages" id="live-messages">
                    ${this.messages.length === 0 ? '<div class="live-empty">Waiting for messages...</div>' : ''}
                    ${this.messages.map(m => this._renderBubble(m)).join('')}
                </div>
                <div class="live-scroll-btn" id="live-scroll-btn" onclick="GhostLive.scrollToBottom()" style="display:none;">
                    &#8595; New messages
                </div>
                <div class="live-input-area">
                    <input type="text" id="live-input" class="live-input" placeholder="Type a question..." autocomplete="off" spellcheck="false"
                        onkeydown="if(event.key==='Enter'){GhostLive.sendMessage();event.preventDefault();}">
                    <button class="live-send-btn" onclick="GhostLive.sendMessage()">&#9654;</button>
                </div>
            </div>`;
        this._setupScrollDetection();
        if (this.autoScroll) {
            this._scrollToBottom();
        }
    },

    _renderBubble(msg) {
        const alignClass = msg.isOwn ? 'live-bubble-own' : 'live-bubble-sender';
        const editedTag = msg.edited ? '<span class="live-edited">(edited)</span>' : '';
        const time = this._formatTime(msg.timestamp);
        const formatted = this.formatMessage(msg.text);
        return `<div class="live-bubble ${alignClass}" data-id="${this.escapeHtml(msg.id)}">
            <div class="live-bubble-text">${formatted}${editedTag}</div>
            <div class="live-bubble-time">${time}</div>
        </div>`;
    },

    addMessage(id, text, timestamp, isOwn) {
        this.messages.push({ id: id, text: text, timestamp: timestamp, isOwn: isOwn, edited: false });
        const container = document.getElementById('live-messages');
        if (!container) {
            this.render();
            return;
        }
        // Remove empty state
        const empty = container.querySelector('.live-empty');
        if (empty) empty.remove();

        const msg = { id: id, text: text, timestamp: timestamp, isOwn: isOwn, edited: false };
        container.insertAdjacentHTML('beforeend', this._renderBubble(msg));

        if (this.autoScroll) {
            this._scrollToBottom();
        } else {
            this.showNewIndicator();
        }
    },

    editMessage(id, newText) {
        // Update stored message
        const msg = this.messages.find(m => m.id === id);
        if (msg) {
            msg.text = newText;
            msg.edited = true;
        }
        // Update DOM
        const bubble = document.querySelector(`.live-bubble[data-id="${id}"]`);
        if (bubble) {
            const textEl = bubble.querySelector('.live-bubble-text');
            if (textEl) {
                textEl.innerHTML = this.formatMessage(newText) + '<span class="live-edited">(edited)</span>';
            }
        }
    },

    deleteMessage(id) {
        this.messages = this.messages.filter(m => m.id !== id);
        const bubble = document.querySelector(`.live-bubble[data-id="${id}"]`);
        if (bubble) {
            bubble.classList.add('live-bubble-fade');
            setTimeout(() => bubble.remove(), 300);
        }
    },

    setRoomInfo(code, status) {
        this.roomCode = code;
        this.status = status;
        const codeEl = document.querySelector('.live-room-code');
        const statusEl = document.querySelector('.live-status');
        if (codeEl) {
            codeEl.textContent = code ? 'Room: ' + code : 'Live Chat';
        }
        if (statusEl) {
            statusEl.textContent = this._statusText();
            statusEl.className = 'live-status live-status-' + status;
        }
    },

    showNewIndicator() {
        const btn = document.getElementById('live-scroll-btn');
        if (btn) btn.style.display = 'block';
    },

    hideNewIndicator() {
        const btn = document.getElementById('live-scroll-btn');
        if (btn) btn.style.display = 'none';
    },

    scrollToBottom() {
        this.autoScroll = true;
        this.hideNewIndicator();
        this._scrollToBottom();
    },

    sendMessage() {
        const input = document.getElementById('live-input');
        if (!input) return;
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        // Notify Python to send the message
        window.webkit.messageHandlers.ghost.postMessage({ action: 'live_send', text: text });
    },

    _scrollToBottom() {
        requestAnimationFrame(() => {
            const container = document.getElementById('live-messages');
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        });
    },

    _setupScrollDetection() {
        requestAnimationFrame(() => {
            const container = document.getElementById('live-messages');
            if (!container) return;
            container.addEventListener('scroll', () => {
                const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50;
                this.autoScroll = atBottom;
                if (atBottom) {
                    this.hideNewIndicator();
                }
            });
        });
    },

    _statusText() {
        switch (this.status) {
            case 'connected': return 'Connected';
            case 'connecting': return 'Connecting...';
            case 'disconnected': return 'Disconnected';
            case 'error': return 'Error';
            default: return this.status;
        }
    },

    _formatTime(timestamp) {
        if (!timestamp) return '';
        try {
            const d = new Date(timestamp);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            return timestamp;
        }
    },

    // ── Code Detection & Formatting ──

    formatMessage(text) {
        // 1. Handle markdown fenced code blocks: ```lang\ncode\n```
        if (/```/.test(text)) {
            return this._processMarkdownBlocks(text);
        }

        // 2. Handle inline code: `code`
        if (/`[^`]+`/.test(text)) {
            return this._processInlineCode(text);
        }

        // 3. Auto-detect code (no markdown markers)
        if (this._looksLikeCode(text)) {
            return this._renderCodeBlock(text, this._guessLanguage(text));
        }

        // 4. Plain text
        return this.escapeHtml(text);
    },

    _processMarkdownBlocks(text) {
        const parts = text.split(/(```[\s\S]*?```)/g);
        return parts.map(part => {
            const match = part.match(/^```(\w*)\n?([\s\S]*?)```$/);
            if (match) {
                const lang = match[1] || this._guessLanguage(match[2]);
                return this._renderCodeBlock(match[2], lang);
            }
            // Process remaining text for inline code
            if (/`[^`]+`/.test(part)) {
                return this._processInlineCode(part);
            }
            return this.escapeHtml(part);
        }).join('');
    },

    _processInlineCode(text) {
        const parts = text.split(/(`[^`]+`)/g);
        return parts.map(part => {
            const match = part.match(/^`([^`]+)`$/);
            if (match) {
                return `<code class="code-inline">${this.escapeHtml(match[1])}</code>`;
            }
            return this.escapeHtml(part);
        }).join('');
    },

    _looksLikeCode(text) {
        const lines = text.split('\n');

        // Strong single-line signals (definitely code even on 1 line)
        const strongPatterns = [
            /^\s*(def |class |import |from \w+ import)/,         // Python
            /^\s*(public |private |protected ).*[{;]\s*$/,       // Java
            /^\s*@\w+/,                                          // Decorator/annotation
            /^\s*(System\.out|print\(|console\.log)/,            // Print statements
        ];
        for (const p of strongPatterns) {
            if (p.test(text)) return true;
        }

        if (lines.length < 2) return false;

        let codeSignals = 0;

        // Indentation pattern (2+ lines start with spaces/tabs)
        const indented = lines.filter(l => /^[\t ]/.test(l)).length;
        if (indented >= 2) codeSignals++;

        // Semicolons at end of lines (Java/C)
        const semiLines = lines.filter(l => /;\s*$/.test(l.trim())).length;
        if (semiLines >= 2) codeSignals += 2;

        // Python-style colons at end of lines (def, class, if, for, etc.)
        const colonLines = lines.filter(l => /:\s*$/.test(l.trim())).length;
        if (colonLines >= 1) codeSignals++;

        // Common code patterns
        const codePatterns = [
            /[{}\[\]();]/,                                    // Brackets, semicolons
            /\b(def |class |import |from |return |self\.)/,   // Python
            /\b(function |const |let |var |=>)/,              // JavaScript
            /\b(public |private |static |void |throws )/,     // Java
            /\b(SELECT |FROM |WHERE |INSERT |CREATE )/i,      // SQL
            /\b(if\s*\(|for\s*\(|while\s*\()/,               // C-style control flow
            /^\s*(#include|#define)/m,                         // C/C++
            /[=!<>]=|&&|\|\|/,                                // Operators
            /\b(System\.out|println|printf)\b/,               // Java print
            /\b(print|len|range|enumerate)\s*\(/,             // Python builtins
        ];

        for (const p of codePatterns) {
            if (p.test(text)) codeSignals++;
        }

        return codeSignals >= 2;
    },

    _guessLanguage(code) {
        // Score each language — highest score wins
        const scores = { python: 0, java: 0, javascript: 0, sql: 0, go: 0, rust: 0, cpp: 0 };

        // Python signals
        if (/\bdef\s+\w+\s*\(/.test(code)) scores.python += 3;
        if (/\bself\.\w+/.test(code)) scores.python += 3;
        if (/\bimport\s+\w+/.test(code) && !/;/.test(code)) scores.python += 2;
        if (/\bfrom\s+\w+\s+import/.test(code)) scores.python += 3;
        if (/\belif\b/.test(code)) scores.python += 3;
        if (/\bprint\s*\(/.test(code)) scores.python += 2;
        if (/:\s*$/m.test(code)) scores.python += 2;
        if (/@\w+\s*\n\s*def\b/.test(code)) scores.python += 3;
        if (/\b(None|True|False)\b/.test(code)) scores.python += 1;
        if (/\blen\(|\brange\(|\benumerate\(|\bzip\(/.test(code)) scores.python += 2;
        if (/\blambda\b/.test(code)) scores.python += 2;
        if (/\b(list|dict|tuple|set)\s*\(/.test(code)) scores.python += 1;
        if (/f"[^"]*\{/.test(code) || /f'[^']*\{/.test(code)) scores.python += 2;
        if (/"""[\s\S]*?"""/.test(code) || /'''[\s\S]*?'''/.test(code)) scores.python += 2;
        if (/\b(yield|with|as|except|raise)\b/.test(code)) scores.python += 1;

        // Java signals
        if (/\bpublic\s+(static\s+)?(\w+\s+)+\w+\s*\(/.test(code)) scores.java += 3;
        if (/\bSystem\.out\.print/.test(code)) scores.java += 3;
        if (/;\s*$/m.test(code)) scores.java += 1;
        if (/\b(String|Integer|Long|Double|Boolean|ArrayList|HashMap|List|Map|Set)\b/.test(code)) scores.java += 2;
        if (/\b(public|private|protected)\s+(static\s+)?(void|int|String|boolean|long|double|float|char)\b/.test(code)) scores.java += 3;
        if (/\bnew\s+\w+\s*[<(]/.test(code)) scores.java += 2;
        if (/@(Override|Deprecated|SuppressWarnings|Test|Bean|Autowired|Component|Service|Repository|Controller)/.test(code)) scores.java += 3;
        if (/\b(extends|implements)\b/.test(code)) scores.java += 3;
        if (/\bimport\s+[\w.]+;/.test(code)) scores.java += 3;
        if (/\bthrows\s+\w+/.test(code)) scores.java += 2;
        if (/\binstanceof\b/.test(code)) scores.java += 2;
        if (/\b(try|catch)\s*\(/.test(code) && /;\s*$/m.test(code)) scores.java += 1;
        if (/\bnull\b/.test(code) && /;\s*$/m.test(code)) scores.java += 1;

        // JavaScript signals
        if (/\b(const|let|var)\s+\w+\s*=/.test(code)) scores.javascript += 2;
        if (/=>\s*[{(]/.test(code)) scores.javascript += 3;
        if (/\bconsole\.\w+/.test(code)) scores.javascript += 3;
        if (/\brequire\s*\(/.test(code)) scores.javascript += 2;
        if (/\bmodule\.exports/.test(code)) scores.javascript += 3;

        // SQL signals
        if (/\b(SELECT|INSERT|UPDATE|DELETE|CREATE)\b/i.test(code)) scores.sql += 3;
        if (/\b(FROM|WHERE|JOIN|GROUP BY|ORDER BY)\b/i.test(code)) scores.sql += 2;

        // Find highest
        let best = '';
        let bestScore = 0;
        for (const [lang, score] of Object.entries(scores)) {
            if (score > bestScore) {
                bestScore = score;
                best = lang;
            }
        }
        return bestScore >= 2 ? best : '';
    },

    _renderCodeBlock(code, lang) {
        const escaped = this.escapeHtml(code.replace(/^\n|\n$/g, ''));
        const highlighted = this._highlight(escaped, lang);
        const langBadge = lang ? `<span class="code-lang">${lang}</span>` : '';
        return `<div class="code-block">${langBadge}<pre><code>${highlighted}</code></pre></div>`;
    },

    _highlight(escaped, lang) {
        if (lang === 'python') return this._highlightPython(escaped);
        if (lang === 'java') return this._highlightJava(escaped);
        return this._highlightGeneric(escaped);
    },

    _highlightPython(h) {
        // Triple-quoted strings first (before single-line strings)
        h = h.replace(/(&quot;&quot;&quot;)([\s\S]*?)(\1)/g, '<span class="hl-str">$1$2$3</span>');
        h = h.replace(/(&#39;&#39;&#39;)([\s\S]*?)(\1)/g, '<span class="hl-str">$1$2$3</span>');

        // f-strings: f"..." and f'...'
        h = h.replace(/\bf(&quot;)([\s\S]*?)(&quot;)/g, '<span class="hl-str">f$1$2$3</span>');
        h = h.replace(/\bf(&#39;)([\s\S]*?)(&#39;)/g, '<span class="hl-str">f$1$2$3</span>');

        // Regular strings
        h = h.replace(/(&quot;)([\s\S]*?)(&quot;)/g, '<span class="hl-str">$1$2$3</span>');
        h = h.replace(/(&#39;)([\s\S]*?)(&#39;)/g, '<span class="hl-str">$1$2$3</span>');

        // Comments
        h = h.replace(/(#.*)$/gm, '<span class="hl-cmt">$1</span>');

        // Decorators
        h = h.replace(/(@\w+)/g, '<span class="hl-dec">$1</span>');

        // Keywords
        const kw = 'def|class|import|from|return|if|else|elif|for|while|in|not|and|or|is|' +
            'try|except|finally|with|as|yield|async|await|pass|raise|lambda|global|nonlocal|' +
            'assert|del|break|continue';
        h = h.replace(new RegExp(`\\b(${kw})\\b`, 'g'), '<span class="hl-kw">$1</span>');

        // Built-in functions
        const builtins = 'print|len|range|str|int|float|list|dict|set|tuple|sorted|enumerate|' +
            'zip|map|filter|open|isinstance|type|super|input|abs|max|min|sum|any|all|' +
            'hasattr|getattr|setattr|delattr|repr|iter|next|reversed|round|format|' +
            'staticmethod|classmethod|property';
        h = h.replace(new RegExp(`\\b(${builtins})(\\()`, 'g'), '<span class="hl-fn">$1</span>$2');

        // Special values
        h = h.replace(/\b(True|False|None|self|cls)\b/g, '<span class="hl-val">$1</span>');

        // Numbers
        h = h.replace(/\b(\d+\.?\d*)\b/g, '<span class="hl-num">$1</span>');

        // Type hints after -> and :
        h = h.replace(/-&gt;\s*(\w+)/g, '-&gt; <span class="hl-typ">$1</span>');

        return h;
    },

    _highlightJava(h) {
        // Multi-line comments /* */
        h = h.replace(/(\/\*[\s\S]*?\*\/)/g, '<span class="hl-cmt">$1</span>');

        // Single-line strings
        h = h.replace(/(&quot;)([\s\S]*?)(&quot;)/g, '<span class="hl-str">$1$2$3</span>');
        h = h.replace(/(&#39;)([\s\S]*?)(&#39;)/g, '<span class="hl-str">$1$2$3</span>');

        // Single-line comments
        h = h.replace(/(\/\/.*)$/gm, '<span class="hl-cmt">$1</span>');

        // Annotations
        h = h.replace(/(@\w+)/g, '<span class="hl-dec">$1</span>');

        // Keywords
        const kw = 'abstract|assert|break|case|catch|class|continue|default|do|else|enum|' +
            'extends|final|finally|for|if|implements|import|instanceof|interface|' +
            'native|new|package|private|protected|public|return|static|strictfp|super|' +
            'switch|synchronized|this|throw|throws|transient|try|volatile|while|void';
        h = h.replace(new RegExp(`\\b(${kw})\\b`, 'g'), '<span class="hl-kw">$1</span>');

        // Primitive types
        const prims = 'boolean|byte|char|double|float|int|long|short';
        h = h.replace(new RegExp(`\\b(${prims})\\b`, 'g'), '<span class="hl-typ">$1</span>');

        // Common class types (capitalized words used as types)
        const types = 'String|Integer|Long|Double|Float|Boolean|Character|Byte|Short|' +
            'Object|Class|System|Math|Arrays|Collections|' +
            'List|ArrayList|LinkedList|Map|HashMap|TreeMap|LinkedHashMap|' +
            'Set|HashSet|TreeSet|Queue|Stack|Deque|ArrayDeque|PriorityQueue|' +
            'Optional|Stream|Collectors|Iterator|Iterable|Comparable|Comparator|' +
            'Exception|RuntimeException|IOException|NullPointerException|' +
            'StringBuilder|StringBuffer|Thread|Runnable|Callable|Future';
        h = h.replace(new RegExp(`\\b(${types})\\b`, 'g'), '<span class="hl-typ">$1</span>');

        // Special values
        h = h.replace(/\b(true|false|null)\b/g, '<span class="hl-val">$1</span>');

        // Numbers
        h = h.replace(/\b(\d+[Ll]?\.?\d*[fFdD]?)\b/g, '<span class="hl-num">$1</span>');

        // Method calls: word followed by (
        h = h.replace(/\b([a-z]\w*)\s*\(/g, '<span class="hl-fn">$1</span>(');

        return h;
    },

    _highlightGeneric(h) {
        // Strings
        h = h.replace(/(&quot;)([\s\S]*?)(&quot;)/g, '<span class="hl-str">$1$2$3</span>');
        h = h.replace(/(&#39;)([\s\S]*?)(&#39;)/g, '<span class="hl-str">$1$2$3</span>');

        // Comments
        h = h.replace(/(\/\/.*)$/gm, '<span class="hl-cmt">$1</span>');
        h = h.replace(/(#.*)$/gm, '<span class="hl-cmt">$1</span>');
        h = h.replace(/(\/\*[\s\S]*?\*\/)/g, '<span class="hl-cmt">$1</span>');

        // Keywords
        const kw = 'def|class|import|from|return|if|else|elif|for|while|in|not|and|or|try|except|finally|' +
            'with|as|yield|async|await|function|const|let|var|new|this|throw|catch|switch|case|break|continue|' +
            'public|private|static|void|int|float|double|string|bool|boolean|char|long|' +
            'true|false|null|None|nil|undefined|self|super';
        h = h.replace(new RegExp(`\\b(${kw})\\b`, 'g'), '<span class="hl-kw">$1</span>');

        // Numbers
        h = h.replace(/\b(\d+\.?\d*)\b/g, '<span class="hl-num">$1</span>');

        return h;
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    GhostLive.init();
});
