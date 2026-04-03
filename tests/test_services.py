import importlib
import sys


def load_quiz_service():
    sys.modules.pop('src.services.quiz_service', None)
    import src.services.quiz_service as quiz_service
    return importlib.reload(quiz_service)


def load_rag_service():
    sys.modules.pop('src.services.rag_service', None)
    import src.services.rag_service as rag_service
    return importlib.reload(rag_service)


def test_quiz_service_parse_mcq_valid():
    quiz_service = load_quiz_service()
    raw = (
        'Q: Which layer handles routing?\n'
        'A) Data Link\n'
        'B) Network\n'
        'C) Transport\n'
        'D) Session\n'
        'Answer: B\n'
        'Explanation: The network layer handles logical routing.\n'
    )
    parsed = quiz_service.parse_mcq_question(raw)
    assert parsed is not None
    assert parsed['answer'] == 'B'
    assert len(parsed['options']) == 4


def test_quiz_service_parse_mcq_invalid():
    quiz_service = load_quiz_service()
    raw = 'Q: Missing options\nA) One\nB) Two\nAnswer: A\n'
    assert quiz_service.parse_mcq_question(raw) is None


def test_rag_service_save_list_clear(tmp_path, monkeypatch):
    rag_service = load_rag_service()
    uploads_dir = tmp_path / 'uploads'
    uploads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rag_service, 'UPLOAD_DIR', str(uploads_dir))

    path = rag_service.save_uploaded_file(b'pdf-bytes', 'notes.pdf')
    files = rag_service.list_uploaded_files()

    assert path.endswith('notes.pdf')
    assert files == ['notes.pdf']

    rag_service.clear_uploads()
    assert rag_service.list_uploaded_files() == []
