// Ghost SCREEN box — shows "what Ghost sees" (live screen OCR), styled like the
// Ghost AI panel with a plain background. Driven from Python via SCREEN.set(text).

const SCREEN = {
    init() {
        document.body.innerHTML = `
            <div id="screen">
                <div class="screen-bar">
                    <span class="screen-dot"></span>
                    <span class="screen-title">Screen — what Ghost sees</span>
                </div>
                <div class="screen-body" id="screen-body">
                    <div class="screen-empty">Waiting for the screen…</div>
                </div>
            </div>`;
    },

    set(text) {
        const body = document.getElementById('screen-body');
        if (!body) return;
        if (text && text.trim()) {
            body.textContent = text;
        } else {
            body.innerHTML = `<div class="screen-empty">Nothing readable on screen</div>`;
        }
        body.scrollTop = 0;
    },

    status(msg) {
        const el = document.getElementById('screen-title');
        if (el && msg) el.textContent = msg;
    }
};

document.addEventListener('DOMContentLoaded', () => SCREEN.init());
