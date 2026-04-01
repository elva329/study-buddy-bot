import os
import shutil
from typing import List, Dict, Tuple


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


def retrieve_relevant_chunks(query: str, chunks: List[Dict], top_k: int = 3) -> List[Dict]:
    """
    Retrieve top K relevant chunks based on meaningful keyword overlap with query.
    Filters out common stop words and requires significant keyword matching.
    Returns list of chunks sorted by relevance.
    """
    if not chunks:
        return []

    # Common stop words to filter out
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'is', 'are', 'was', 'be', 'been', 'being', 'have', 'has', 'had',
        'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
        'can', 'what', 'which', 'who', 'when', 'where', 'why', 'how', 'this',
        'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they'
    }

    # Extract meaningful (non-stop) words from query
    query_words = set(
        word.lower() for word in query.split()
        if word.lower() not in stop_words and len(word) > 2
    )

    if not query_words:
        return []  # All words were stop words

    def calculate_relevance(chunk_text: str) -> int:
        """Count matching meaningful keywords in chunk"""
        chunk_words = set(
            word.lower() for word in chunk_text.split()
            if word.lower() not in stop_words and len(word) > 2
        )
        return len(query_words & chunk_words)

    # Score each chunk
    scored_chunks = []
    for chunk in chunks:
        score = calculate_relevance(chunk['text'])
        if score >= 2:  # Require at least 2 meaningful keyword matches
            scored_chunks.append((chunk, score))

    # Sort by relevance (descending) and return top K
    scored_chunks.sort(key=lambda x: x[1], reverse=True)
    return [chunk for chunk, score in scored_chunks[:top_k]]
