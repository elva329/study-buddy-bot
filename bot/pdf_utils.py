import os
from typing import List, Tuple, Dict
from PyPDF2 import PdfReader


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


def extract_texts_with_metadata(upload_dir: str) -> List[Dict]:
    """
    Extract text from all PDFs in the upload directory with source tracking.
    Returns a list of dicts with keys: 'text', 'filename', 'page_num'
    """
    chunks = []
    for fname in os.listdir(upload_dir):
        if fname.lower().endswith('.pdf'):
            pdf_path = os.path.join(upload_dir, fname)
            try:
                reader = PdfReader(pdf_path)
                for page_num, page in enumerate(reader.pages, 1):
                    text = page.extract_text() or ""
                    if text.strip():
                        chunks.append({
                            'text': text,
                            'filename': fname,
                            'page_num': page_num
                        })
            except Exception as e:
                print(f"[PDF Error] Failed to extract from {fname}: {e}")
    return chunks
