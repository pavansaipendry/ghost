import os

from ghost.documents import txt_parser, md_parser, pdf_parser, docx_parser

SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx"}

_PARSERS = {
    ".txt": txt_parser.parse,
    ".md": md_parser.parse,
    ".markdown": md_parser.parse,
    ".pdf": pdf_parser.parse,
    ".docx": docx_parser.parse,
}


def load_document(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in _PARSERS:
        raise ValueError(f"Unsupported file type: {ext}")
    return _PARSERS[ext](filepath)


def get_extension(filepath):
    return os.path.splitext(filepath)[1].lower().lstrip(".")


def is_supported(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    return ext in SUPPORTED_EXTENSIONS
