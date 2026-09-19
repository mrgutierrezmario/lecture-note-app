"""Text extraction for uploaded documents (PDF, PowerPoint, Word).

Images have no text layer and are handled by the vision providers instead;
``image_media_type`` only identifies them.
"""

import io
import logging

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Concatenate the text of every page (pdfplumber)."""
    import pdfplumber

    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text.strip())
    return "\n\n".join(text_parts)


def extract_text_from_pptx(file_bytes: bytes) -> str:
    """Text of every shape on every slide, labelled by slide number."""
    from pptx import Presentation

    prs = Presentation(io.BytesIO(file_bytes))
    text_parts = []
    for slide_num, slide in enumerate(prs.slides, 1):
        slide_texts = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_texts.append(shape.text.strip())
        if slide_texts:
            text_parts.append(f"[Slide {slide_num}]\n" + "\n".join(slide_texts))
    return "\n\n".join(text_parts)


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Paragraph text plus table rows (tab-separated) from a .docx file.
    Legacy binary .doc is not supported by python-docx.
    """
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    text_parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text.strip())
    # Tables are not part of doc.paragraphs; flatten each row as tab-separated cells.
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                text_parts.append("\t".join(cells))
    return "\n\n".join(text_parts)


IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def image_media_type(filename: str) -> str | None:
    """Media type for an image upload, or None if the name is not an image."""
    lower = filename.lower()
    for ext, media_type in IMAGE_MEDIA_TYPES.items():
        if lower.endswith(ext):
            return media_type
    return None


def extract_text(filename: str, file_bytes: bytes) -> tuple[str, str]:
    """Returns (file_type, extracted_text)"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "pdf", extract_text_from_pdf(file_bytes)
    elif lower.endswith(".pptx") or lower.endswith(".ppt"):
        return "pptx", extract_text_from_pptx(file_bytes)
    elif lower.endswith(".docx"):
        return "docx", extract_text_from_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {filename}")
