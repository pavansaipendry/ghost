import html as html_module
from docx import Document
from docx.oxml.ns import qn


def parse(filepath):
    doc = Document(filepath)
    raw_parts = []

    for element in doc.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "p":
            raw_parts.append(_parse_paragraph(element, doc))
        elif tag == "tbl":
            raw_parts.append(_parse_table(element, doc))

    # Group consecutive <li> items into <ul> blocks
    parts = []
    in_list = False
    for part in raw_parts:
        if part.startswith("<li>"):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(part)
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(part)
    if in_list:
        parts.append("</ul>")

    return "\n".join(parts)


def _parse_paragraph(element, doc):
    # Check heading style
    style = ""
    pPr = element.find(qn("w:pPr"))
    if pPr is not None:
        pStyle = pPr.find(qn("w:pStyle"))
        if pStyle is not None:
            style = pStyle.get(qn("w:val"), "")

    text_parts = []
    for run in element.findall(qn("w:r")):
        text = "".join(t.text or "" for t in run.findall(qn("w:t")))
        if not text:
            continue

        # Check formatting
        rPr = run.find(qn("w:rPr"))
        bold = False
        italic = False
        underline = False
        if rPr is not None:
            bold = rPr.find(qn("w:b")) is not None
            italic = rPr.find(qn("w:i")) is not None
            underline = rPr.find(qn("w:u")) is not None

        escaped = html_module.escape(text)
        if bold:
            escaped = f"<strong>{escaped}</strong>"
        if italic:
            escaped = f"<em>{escaped}</em>"
        if underline:
            escaped = f"<u>{escaped}</u>"
        text_parts.append(escaped)

    content = "".join(text_parts)
    if not content.strip():
        return ""

    # Map heading styles
    if style.startswith("Heading"):
        try:
            level = int(style.replace("Heading", "").strip())
            level = min(level, 6)
        except ValueError:
            level = 1
        return f"<h{level}>{content}</h{level}>"

    # Check for list
    numPr = None
    if pPr is not None:
        numPr = pPr.find(qn("w:numPr"))
    if numPr is not None:
        return f"<li>{content}</li>"

    return f"<p>{content}</p>"


def _parse_table(element, doc):
    rows_html = []
    rows = element.findall(qn("w:tr"))

    for i, row in enumerate(rows):
        cells = row.findall(qn("w:tc"))
        tag = "th" if i == 0 else "td"
        cells_html = []
        for cell in cells:
            text = ""
            for p in cell.findall(qn("w:p")):
                for run in p.findall(qn("w:r")):
                    text += "".join(t.text or "" for t in run.findall(qn("w:t")))
            cells_html.append(f"<{tag}>{html_module.escape(text)}</{tag}>")
        rows_html.append(f"<tr>{''.join(cells_html)}</tr>")

    return f"<table>{''.join(rows_html)}</table>"
