import importlib
import os
import sys


def reload_db_client(monkeypatch, env):
    keys = [
        'DATABASE_URL', 'DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME', 'DB_PORT',
        'REQUIRE_CLOUD_DB'
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop('database.db_client', None)
    import database.db_client as db_client
    return importlib.reload(db_client)


def test_database_persistence_smoke(tmp_path, monkeypatch):
    db_path = tmp_path / 'studybuddy.db'
    db_client = reload_db_client(monkeypatch, {
        'DATABASE_URL': f'sqlite:///{db_path}'
    })

    db_client.log_message(42, 'hello bot', 'user')
    db_client.log_event(42, 'pdf_uploaded', {'filename': 'notes.pdf'})
    db_client.log_quiz_attempt_db(42, 5)
    db_client.log_quiz_score(42, 4, 5, 80, {'Databases': (3, 4)})

    history = db_client.get_quiz_history(42, limit=5)
    assert len(history) == 1
    assert history[0][1] == 5

    total_quizzes, avg_score, best_score, worst_score, weak_topic = db_client.get_quiz_stats(
        42)
    assert total_quizzes == 1
    assert avg_score == 80
    assert best_score == 80
    assert worst_score == 80
    assert weak_topic == 'Databases'

    progress = db_client.get_user_progress_db(42)
    assert len(progress) == 1
    assert progress[0]['num_questions'] == 5

    overview = db_client.get_db_overview()
    assert overview['messages'] == 1
    assert overview['events'] == 1
    assert overview['quiz_attempts'] == 1
    assert overview['quiz_scores'] == 1
    assert overview['topic_scores'] == 1


def test_db_host_full_url_is_accepted(monkeypatch):
    db_client = reload_db_client(monkeypatch, {
        'DB_HOST': 'postgresql://user:pass@db.example.com:5432/mydb'
    })
    assert db_client.DB_URL == 'postgresql://user:pass@db.example.com:5432/mydb'


def test_db_host_components_compose_postgres_url(monkeypatch):
    db_client = reload_db_client(monkeypatch, {
        'DB_HOST': 'db.example.com',
        'DB_USER': 'alice',
        'DB_PASSWORD': 'p@ss',
        'DB_NAME': 'study',
        'DB_PORT': '5432',
    })
    assert db_client.DB_URL.startswith('postgresql://alice:')
    assert '@db.example.com:5432/study' in db_client.DB_URL


def test_require_cloud_db_rejects_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / 'fallback.db'
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')
    monkeypatch.setenv('REQUIRE_CLOUD_DB', 'true')
    sys.modules.pop('database.db_client', None)

    try:
        import database.db_client  # noqa: F401
    except RuntimeError as exc:
        assert 'REQUIRE_CLOUD_DB' in str(exc)
    else:
        raise AssertionError(
            'Expected RuntimeError when REQUIRE_CLOUD_DB=true with sqlite')
