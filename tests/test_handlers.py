import importlib
import sys


def load_bot_main(monkeypatch, tmp_path):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setenv(
        'DATABASE_URL', f'sqlite:///{tmp_path / "handler-test.db"}')
    sys.modules.pop('bot.main', None)
    import bot.main as bot_main
    return importlib.reload(bot_main)


def test_strip_markdown(monkeypatch, tmp_path):
    bot_main = load_bot_main(monkeypatch, tmp_path)
    text = '### Title\n**Bold** _Italic_ `code` [link](https://example.com)'
    cleaned = bot_main.strip_markdown(text)
    assert 'Title' in cleaned
    assert 'Bold' in cleaned
    assert 'Italic' in cleaned
    assert 'link' in cleaned
    assert 'https://example.com' not in cleaned


def test_parse_mcq_question_valid(monkeypatch, tmp_path):
    bot_main = load_bot_main(monkeypatch, tmp_path)
    raw = (
        'Q: What is SQL?\n'
        'A) A query language\n'
        'B) A web server\n'
        'C) A browser\n'
        'D) A firewall\n'
        'Answer: A\n'
        'Explanation: SQL is used to query relational databases.\n'
    )
    parsed = bot_main.parse_mcq_question(raw)
    assert parsed is not None
    assert parsed['answer'] == 'A'
    assert len(parsed['options']) == 4


def test_parse_mcq_question_invalid(monkeypatch, tmp_path):
    bot_main = load_bot_main(monkeypatch, tmp_path)
    raw = 'Q: broken\nA) only one option\nAnswer: A\n'
    assert bot_main.parse_mcq_question(raw) is None


def test_looks_like_mcq_output(monkeypatch, tmp_path):
    bot_main = load_bot_main(monkeypatch, tmp_path)
    assert bot_main.looks_like_mcq_output('Question 1\nA) x\nB) y') is True
    assert bot_main.looks_like_mcq_output('Correct answer: C') is True
    assert bot_main.looks_like_mcq_output(
        'This is a normal paragraph response.') is False
