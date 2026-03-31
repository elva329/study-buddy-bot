# PDF extraction logic


from PyPDF2 import PdfReader
import os
from typing import List


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file."""
    reader = PdfReader(pdf_path)
    text = []
    for page in reader.pages:
        text.append(page.extract_text() or "")
    return "\n".join(text)


def extract_texts_from_all_pdfs(upload_dir: str) -> List[str]:
    """Extract text from all PDFs in the upload directory."""
    texts = []
    for fname in os.listdir(upload_dir):
        if fname.lower().endswith('.pdf'):
            pdf_path = os.path.join(upload_dir, fname)
            texts.append(extract_text_from_pdf(pdf_path))
    return texts
