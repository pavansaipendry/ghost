import html


def parse(filepath):
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    escaped = html.escape(text)
    return f'<div class="plaintext">{escaped}</div>'
