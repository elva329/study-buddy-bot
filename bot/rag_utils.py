import os
import shutil
from typing import List

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')

os.makedirs(UPLOAD_DIR, exist_ok=True)


def save_uploaded_file(file_bytes: bytes, filename: str) -> str:
    """Save uploaded file to the uploads directory and return the file path."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, 'wb') as f:
        f.write(file_bytes)
    return file_path


def list_uploaded_files() -> List[str]:
    """List all uploaded files."""
    return [f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f))]


def clear_uploads():
    """Delete all uploaded files."""
    shutil.rmtree(UPLOAD_DIR)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
