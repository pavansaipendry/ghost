import markdown
from pygments.formatters import HtmlFormatter

# Generate Pygments CSS for syntax highlighting (monokai-ish dark theme)
_PYGMENTS_CSS = HtmlFormatter(style="monokai").get_style_defs(".codehilite")

_MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "codehilite",
    "toc",
    "nl2br",
    "sane_lists",
]

_MD_EXT_CONFIGS = {
    "codehilite": {
        "css_class": "codehilite",
        "guess_lang": True,
    }
}


def parse(filepath):
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    md = markdown.Markdown(extensions=_MD_EXTENSIONS, extension_configs=_MD_EXT_CONFIGS)
    html_content = md.convert(text)

    return f"<style>{_PYGMENTS_CSS}</style>\n{html_content}"
