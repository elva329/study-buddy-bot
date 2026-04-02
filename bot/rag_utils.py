import os
import shutil
import re
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

    def normalize_text(text: str) -> str:
        return re.sub(r'[^a-z0-9\s]+', ' ', text.lower())

    def words(text: str) -> List[str]:
        return [word for word in normalize_text(text).split() if word and word not in stop_words]

    def acronym_from_words(word_list: List[str]) -> str:
        return ''.join(word[0] for word in word_list if word)

    # Extract meaningful (non-stop) words from query while preserving order
    ordered_query_words = [word.lower() for word in normalize_text(query).split()
                           if word.lower() not in stop_words and len(word) > 2]
    query_words = set(ordered_query_words)
    query_phrase = " ".join(ordered_query_words)
    query_is_acronym = len(ordered_query_words) == 1 and ordered_query_words[0].isalpha(
    ) and len(ordered_query_words[0]) <= 6
    query_acronym = ordered_query_words[0] if query_is_acronym else ''

    if not query_words:
        return []  # All words were stop words

    def calculate_relevance(chunk_text: str) -> int:
        """Score chunk by keyword overlap + exact phrase/heading match bonus."""
        normalized_chunk = normalize_text(chunk_text)
        chunk_word_list = words(chunk_text)
        chunk_words = set(chunk_word_list)
        overlap = len(query_words & chunk_words)

        # Strongly prefer chunks containing the full phrase, e.g. "machine learning".
        phrase_bonus = 3 if query_phrase and query_phrase in normalized_chunk else 0

        # Lecture notes often have the key phrase in a heading/caption.
        heading_bonus = 2 if normalized_chunk.startswith(
            query_phrase) or f"{query_phrase}:" in normalized_chunk else 0

        # Favor chunks where the query terms appear close together.
        proximity_bonus = 0
        if len(ordered_query_words) >= 2:
            positions = [normalized_chunk.find(
                word) for word in ordered_query_words if word in normalized_chunk]
            if len(positions) >= 2 and max(positions) - min(positions) < 120:
                proximity_bonus = 1

        acronym_bonus = 0
        if query_is_acronym:
            # Match short acronyms against nearby word initials, e.g. LHS -> left hand side.
            for window_size in range(2, min(6, len(chunk_word_list)) + 1):
                for idx in range(0, len(chunk_word_list) - window_size + 1):
                    window = chunk_word_list[idx:idx + window_size]
                    if acronym_from_words(window) == query_acronym:
                        acronym_bonus = max(acronym_bonus, 4)
                        break
                if acronym_bonus:
                    break

        return overlap + phrase_bonus + heading_bonus + proximity_bonus + acronym_bonus

    # Score each chunk
    scored_chunks = []
    min_overlap = 1 if len(query_words) <= 1 else 2

    for chunk in chunks:
        score = calculate_relevance(chunk['text'])
        normalized_chunk = normalize_text(chunk['text'])
        chunk_words = set(words(chunk['text']))
        overlap = len(query_words & chunk_words)
        acronym_hit = False
        if query_is_acronym:
            chunk_word_list = words(chunk['text'])
            for window_size in range(2, min(6, len(chunk_word_list)) + 1):
                for idx in range(0, len(chunk_word_list) - window_size + 1):
                    if acronym_from_words(chunk_word_list[idx:idx + window_size]) == query_acronym:
                        acronym_hit = True
                        break
                if acronym_hit:
                    break

        # For multi-keyword questions, require stronger overlap to avoid generic matches.
        if overlap >= min_overlap or acronym_hit:
            scored_chunks.append((chunk, score))

    # If the query looks like a specific phrase and we found nothing, relax once but still rank.
    if not scored_chunks and (query_phrase or query_is_acronym):
        for chunk in chunks:
            score = calculate_relevance(chunk['text'])
            if score > 0:
                scored_chunks.append((chunk, score))

    # Sort by relevance (descending) and return top K
    scored_chunks.sort(key=lambda x: x[1], reverse=True)
    return [chunk for chunk, score in scored_chunks[:top_k]]
