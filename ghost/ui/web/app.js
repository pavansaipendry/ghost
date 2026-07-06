// Ghost UI Controller
// Communicates with Python via WKWebView message handlers

const Ghost = {
    currentView: 'list',  // 'list' or 'viewer'
    currentDoc: null,
    fontSize: 15,
    documents: [],         // [{slot: 1, name: "file.pdf", ext: "pdf"}, ...]
    searchVisible: false,
    searchMatches: [],
    searchCurrentIndex: -1,
    scrollPositions: {},    // slot -> scrollTop
    darkText: true,         // true = white text on dark bg, false = dark text on white bg

    init() {
        this.renderList();
    },

    // Called from Python to update the document list
    setDocuments(docs) {
        this.documents = docs;
        if (this.currentView === 'list') {
            this.renderList();
        }
    },

    // Called from Python to display a document's HTML content
    showDocument(slot, name, html) {
        this._saveScrollPosition();
        this.currentDoc = { slot, name };
        this.currentView = 'viewer';
        this.renderViewer(name, html);
        // Restore scroll position after render
        requestAnimationFrame(() => {
            const content = document.getElementById('doc-content');
            if (content && this.scrollPositions[slot] !== undefined) {
                content.scrollTop = this.scrollPositions[slot];
            }
        });
    },

    // Go back to document list -- called from Python (Ctrl+0/Esc) or from UI click
    goBack() {
        this._saveScrollPosition();
        this.currentView = 'list';
        this.currentDoc = null;
        this.renderList();
    },

    _saveScrollPosition() {
        if (this.currentDoc) {
            const content = document.getElementById('doc-content');
            if (content) {
                this.scrollPositions[this.currentDoc.slot] = content.scrollTop;
            }
        }
    },

    // Called when user clicks the back arrow in the UI
    goBackFromUI() {
        this.goBack();
        // Notify Python that user clicked back (so Python state stays in sync)
        window.webkit.messageHandlers.ghost.postMessage({action: 'back'});
    },

    // Render the document list home screen
    renderList() {
        let slotsHtml = '';
        for (let i = 1; i <= 7; i++) {
            const doc = this.documents.find(d => d.slot === i);
            if (doc) {
                slotsHtml += `
                    <div class="doc-slot loaded" onclick="Ghost.requestDoc(${i})">
                        <span class="doc-slot-number">${i}</span>
                        <span class="doc-slot-name">${this.escapeHtml(doc.name)}</span>
                        <span class="doc-slot-ext">${doc.ext.toUpperCase()}</span>
                    </div>`;
            } else {
                slotsHtml += `
                    <div class="doc-slot empty">
                        <span class="doc-slot-number">${i}</span>
                        <span class="doc-slot-name">\u2014</span>
                    </div>`;
            }
        }

        document.body.innerHTML = `
            <div class="ghost-drag-handle">GHOST</div>
            <div class="doc-list">
                ${slotsHtml}
                <div class="doc-list-hint">Ctrl+1\u20137 to open \u00b7 Drop files to load</div>
            </div>`;
    },

    // Render the document viewer
    renderViewer(name, html) {
        document.body.innerHTML = `
            <div class="ghost-drag-handle">GHOST</div>
            <div class="doc-viewer">
                <div class="doc-topbar">
                    <span class="doc-back" onclick="Ghost.goBackFromUI()">\u2190</span>
                    <span class="doc-title">${this.escapeHtml(name)}</span>
                    <div class="doc-font-controls">
                        <span class="doc-font-btn" onclick="Ghost.toggleTheme()" title="Toggle background">\u270E</span>
                        <span class="doc-font-btn" onclick="Ghost.adjustFont(-1)">\u2212</span>
                        <span class="doc-font-btn" onclick="Ghost.adjustFont(1)">+</span>
                    </div>
                </div>
                <div class="doc-content" id="doc-content">
                    ${html}
                </div>
            </div>`;
        this.applyFontSize();
    },

    // Request a document from Python (clicked in the list UI)
    requestDoc(slot) {
        window.webkit.messageHandlers.ghost.postMessage({action: 'open', slot: slot});
    },

    // Adjust font size
    adjustFont(delta) {
        this.fontSize = Math.max(10, Math.min(24, this.fontSize + delta));
        this.applyFontSize();
    },

    applyFontSize() {
        const content = document.getElementById('doc-content');
        if (content) {
            content.style.fontSize = this.fontSize + 'px';
        }
    },

    // ── Search ──

    toggleSearch() {
        if (this.currentView !== 'viewer') return;
        if (this.searchVisible) {
            this.closeSearch();
        } else {
            this.openSearch();
        }
    },

    openSearch() {
        this.searchVisible = true;
        const topbar = document.querySelector('.doc-topbar');
        if (!topbar || document.getElementById('ghost-search-bar')) return;

        const bar = document.createElement('div');
        bar.id = 'ghost-search-bar';
        bar.innerHTML = `
            <input type="text" id="ghost-search-input" placeholder="Find in document..." autocomplete="off" spellcheck="false">
            <span id="ghost-search-count"></span>
            <span class="ghost-search-btn" onclick="Ghost.searchPrev()">&#9650;</span>
            <span class="ghost-search-btn" onclick="Ghost.searchNext()">&#9660;</span>
            <span class="ghost-search-btn" onclick="Ghost.closeSearch()">&#10005;</span>
        `;
        topbar.after(bar);

        const input = document.getElementById('ghost-search-input');
        input.focus();
        input.addEventListener('input', () => this.performSearch(input.value));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { this.closeSearch(); e.preventDefault(); }
            else if (e.key === 'Enter' && e.shiftKey) { this.searchPrev(); e.preventDefault(); }
            else if (e.key === 'Enter') { this.searchNext(); e.preventDefault(); }
        });
    },

    closeSearch() {
        this.searchVisible = false;
        this.clearHighlights();
        this.searchMatches = [];
        this.searchCurrentIndex = -1;
        const bar = document.getElementById('ghost-search-bar');
        if (bar) bar.remove();
    },

    performSearch(query) {
        this.clearHighlights();
        this.searchMatches = [];
        this.searchCurrentIndex = -1;

        const countEl = document.getElementById('ghost-search-count');
        if (!query || query.length < 1) {
            if (countEl) countEl.textContent = '';
            return;
        }

        const content = document.getElementById('doc-content');
        if (!content) return;

        this._highlightTextInNode(content, query.toLowerCase());

        this.searchMatches = Array.from(content.querySelectorAll('.ghost-highlight'));
        if (this.searchMatches.length > 0) {
            this.searchCurrentIndex = 0;
            this._activateMatch(0);
        }
        if (countEl) {
            countEl.textContent = this.searchMatches.length > 0
                ? `${this.searchCurrentIndex + 1}/${this.searchMatches.length}`
                : 'No results';
        }
    },

    _highlightTextInNode(node, query) {
        // Walk text nodes and wrap matches in highlight spans
        const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);

        for (const textNode of textNodes) {
            const parent = textNode.parentNode;
            if (parent.classList && parent.classList.contains('ghost-highlight')) continue;
            if (parent.closest('#ghost-search-bar')) continue;

            const text = textNode.nodeValue;
            const lowerText = text.toLowerCase();
            let idx = lowerText.indexOf(query);
            if (idx === -1) continue;

            const frag = document.createDocumentFragment();
            let lastIdx = 0;
            while (idx !== -1) {
                if (idx > lastIdx) {
                    frag.appendChild(document.createTextNode(text.slice(lastIdx, idx)));
                }
                const mark = document.createElement('span');
                mark.className = 'ghost-highlight';
                mark.textContent = text.slice(idx, idx + query.length);
                frag.appendChild(mark);
                lastIdx = idx + query.length;
                idx = lowerText.indexOf(query, lastIdx);
            }
            if (lastIdx < text.length) {
                frag.appendChild(document.createTextNode(text.slice(lastIdx)));
            }
            parent.replaceChild(frag, textNode);
        }
    },

    clearHighlights() {
        const highlights = document.querySelectorAll('.ghost-highlight');
        highlights.forEach(el => {
            const parent = el.parentNode;
            parent.replaceChild(document.createTextNode(el.textContent), el);
            parent.normalize();
        });
    },

    searchNext() {
        if (this.searchMatches.length === 0) return;
        this.searchCurrentIndex = (this.searchCurrentIndex + 1) % this.searchMatches.length;
        this._activateMatch(this.searchCurrentIndex);
    },

    searchPrev() {
        if (this.searchMatches.length === 0) return;
        this.searchCurrentIndex = (this.searchCurrentIndex - 1 + this.searchMatches.length) % this.searchMatches.length;
        this._activateMatch(this.searchCurrentIndex);
    },

    _activateMatch(index) {
        this.searchMatches.forEach(el => el.classList.remove('ghost-highlight-active'));
        const match = this.searchMatches[index];
        if (match) {
            match.classList.add('ghost-highlight-active');
            match.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        const countEl = document.getElementById('ghost-search-count');
        if (countEl && this.searchMatches.length > 0) {
            countEl.textContent = `${index + 1}/${this.searchMatches.length}`;
        }
    },

    toggleTheme() {
        this.darkText = !this.darkText;
        document.body.classList.toggle('ghost-light-theme', !this.darkText);
    },

    showToast(message) {
        // Remove existing toast if any
        const existing = document.getElementById('ghost-toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.id = 'ghost-toast';
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('ghost-toast-fade');
            setTimeout(() => toast.remove(), 500);
        }, 4000);
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    Ghost.init();

    document.addEventListener('keydown', (e) => {
        // Cmd+F: toggle search
        if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
            e.preventDefault();
            Ghost.toggleSearch();
            return;
        }
        // Skip keyboard shortcuts when typing in search bar
        if (e.target.id === 'ghost-search-input') return;
        // +/= : increase font size
        if (e.key === '+' || e.key === '=') {
            Ghost.adjustFont(1);
            return;
        }
        // - : decrease font size
        if (e.key === '-') {
            Ghost.adjustFont(-1);
            return;
        }
    });
});
