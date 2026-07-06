import base64
import html as html_module
import fitz  # PyMuPDF


def parse(filepath):
    doc = fitz.open(filepath)
    pages_html = []

    for i, page in enumerate(doc):
        # Render page as image
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode("ascii")

        # Extract text with position info for searchable overlay
        text_overlay = _build_text_overlay(page, pix.width, pix.height)

        pages_html.append(
            f'<div class="pdf-page">'
            f'<img src="data:image/png;base64,{b64}" alt="Page {i + 1}">'
            f'{text_overlay}'
            f"</div>"
        )

        if i < len(doc) - 1:
            pages_html.append('<hr class="pdf-page-divider">')

    doc.close()
    return "\n".join(pages_html)


def _build_text_overlay(page, img_width, img_height):
    """Build an invisible text layer positioned over the page image for Cmd+F search."""
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    page_rect = page.rect
    if page_rect.width == 0 or page_rect.height == 0:
        return ""

    spans_html = []
    for block in blocks:
        if block["type"] != 0:  # text block only
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue

                # Calculate position as percentage of page dimensions
                bbox = span["bbox"]
                left = (bbox[0] / page_rect.width) * 100
                top = (bbox[1] / page_rect.height) * 100
                width = ((bbox[2] - bbox[0]) / page_rect.width) * 100
                height = ((bbox[3] - bbox[1]) / page_rect.height) * 100
                font_size = span["size"] * (img_height / page_rect.height) * 0.75

                escaped = html_module.escape(text)
                spans_html.append(
                    f'<span class="pdf-text-span" style="'
                    f"left:{left:.2f}%;top:{top:.2f}%;"
                    f"width:{width:.2f}%;height:{height:.2f}%;"
                    f'font-size:{font_size:.1f}px">'
                    f"{escaped}</span>"
                )

    if not spans_html:
        return ""

    return f'<div class="pdf-text-overlay">{"".join(spans_html)}</div>'
