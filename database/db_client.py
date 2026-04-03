# Store quiz session metadata (for progress tracking, replaces user_progress.json)
import configparser
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
import os
from urllib.parse import quote_plus


def log_quiz_attempt_db(user_id, num_questions, timestamp=None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Create table if not exists
        cur.execute('''
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                num_questions INTEGER,
                timestamp TEXT
            )
        ''' if DB_URL.startswith('sqlite') else '''
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                num_questions INTEGER,
                timestamp TIMESTAMP
            )
        ''')
        # Insert attempt
        if not timestamp:
            timestamp = datetime.now(timezone.utc).isoformat() if DB_URL.startswith(
                'sqlite') else datetime.now(timezone.utc)
        cur.execute(
            'INSERT INTO quiz_attempts (user_id, num_questions, timestamp) VALUES (?, ?, ?)' if DB_URL.startswith('sqlite')
            else 'INSERT INTO quiz_attempts (user_id, num_questions, timestamp) VALUES (%s, %s, %s)',
            (user_id, num_questions, timestamp)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error - quiz_attempts] {e}")

# Fetch quiz session metadata for a user (for progress tracking)


def get_user_progress_db(user_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            'SELECT timestamp, num_questions FROM quiz_attempts WHERE user_id = ? ORDER BY timestamp DESC' if DB_URL.startswith('sqlite')
            else 'SELECT timestamp, num_questions FROM quiz_attempts WHERE user_id = %s ORDER BY timestamp DESC',
            (user_id,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Return as list of dicts
        return [{'timestamp': row[0], 'num_questions': row[1]} for row in rows]
    except Exception as e:
        print(f"[DB Error - get_user_progress_db] {e}")
        return []

# Fetch recent quiz history for a user (timestamp, total questions)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config', 'config.ini'))


def get_db_url():
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        return db_url

    # Backward-compatible env support:
    # - DB_HOST can be a full URL (e.g. postgresql://...)
    # - or DB_HOST + DB_USER + DB_PASSWORD + DB_NAME can be composed
    db_host = os.getenv('DB_HOST')
    if db_host:
        lowered = db_host.lower()
        if lowered.startswith('postgresql://') or lowered.startswith('postgres://') or lowered.startswith('sqlite:///'):
            return db_host

        db_user = os.getenv('DB_USER')
        db_password = os.getenv('DB_PASSWORD')
        db_name = os.getenv('DB_NAME')
        db_port = os.getenv('DB_PORT', '5432')
        if db_user and db_password and db_name:
            safe_user = quote_plus(db_user)
            safe_password = quote_plus(db_password)
            return f'postgresql://{safe_user}:{safe_password}@{db_host}:{db_port}/{db_name}'

    if 'database' in config and 'url' in config['database']:
        return config['database']['url']
    return 'sqlite:///studybuddy.db'


DB_URL = get_db_url()

# Backend selection for DB connection
if DB_URL.startswith('sqlite'):
    import sqlite3

    def get_conn():
        db_path = DB_URL.split('///')[-1]
        return sqlite3.connect(db_path)

    CREATE_TABLE = '''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            sender TEXT,
            timestamp TEXT
        )
    '''
    INSERT = 'INSERT INTO messages (user_id, message, sender, timestamp) VALUES (?, ?, ?, ?)'

    # SQLite-specific query helpers
    def get_quiz_history_query():
        return 'SELECT timestamp, total FROM quiz_scores WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?'

    def get_quiz_stats_query():
        return 'SELECT score, total, percent FROM quiz_scores WHERE user_id = ?'

    def get_topic_stats_query():
        return 'SELECT topic, SUM(correct), SUM(total) FROM topic_scores WHERE user_id = ? GROUP BY topic'

    def get_current_timestamp():
        return datetime.now(timezone.utc).isoformat()

else:
    import psycopg2

    def get_conn():
        return psycopg2.connect(DB_URL)

    CREATE_TABLE = '''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            message TEXT,
            sender VARCHAR(10),
            timestamp TIMESTAMP
        )
    '''
    INSERT = 'INSERT INTO messages (user_id, message, sender, timestamp) VALUES (%s, %s, %s, %s)'

    # PostgreSQL-specific query helpers
    def get_quiz_history_query():
        return 'SELECT timestamp, total FROM quiz_scores WHERE user_id = %s ORDER BY timestamp DESC LIMIT %s'

    def get_quiz_stats_query():
        return 'SELECT score, total, percent FROM quiz_scores WHERE user_id = %s'

    def get_topic_stats_query():
        return 'SELECT topic, SUM(correct), SUM(total) FROM topic_scores WHERE user_id = %s GROUP BY topic'

    def get_current_timestamp():
        return datetime.now(timezone.utc)


def get_quiz_history(user_id, limit=5):
    """Fetch recent quiz history for a user"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        query = get_quiz_history_query()
        cur.execute(query, (user_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Return as list of (timestamp, total)
        return [(row[0], row[1]) for row in rows]
    except Exception as e:
        print(f"[DB Error - get_quiz_history] {e}")
        return []


def log_message(user_id, message, sender):
    """Log a message to the database"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Create table if not exists
        cur.execute(CREATE_TABLE)
        # Insert message
        cur.execute(INSERT, (user_id, message,
                    sender, get_current_timestamp()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error - log_message] {e}")


def log_event(user_id, event_type, payload=None):
    """Store a lightweight bot event for tracing and debugging."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        payload_text = json.dumps(
            payload, ensure_ascii=False) if payload is not None else None

        if DB_URL.startswith('sqlite'):
            cur.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    event_type TEXT,
                    payload TEXT,
                    timestamp TEXT
                )
            ''')
            cur.execute(
                'INSERT INTO events (user_id, event_type, payload, timestamp) VALUES (?, ?, ?, ?)',
                (user_id, event_type, payload_text,
                 datetime.now(timezone.utc).isoformat())
            )
        else:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    event_type VARCHAR(64),
                    payload TEXT,
                    timestamp TIMESTAMP
                )
            ''')
            cur.execute(
                'INSERT INTO events (user_id, event_type, payload, timestamp) VALUES (%s, %s, %s, %s)',
                (user_id, event_type, payload_text, datetime.now(timezone.utc))
            )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error - log_event] {e}")


def log_quiz_score(user_id, score, total, percent, topic_scores=None):
    """Store quiz score in the database for progress tracking"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Create table for overall quiz scores
        if DB_URL.startswith('sqlite'):
            cur.execute('''
                CREATE TABLE IF NOT EXISTS quiz_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    score INTEGER,
                    total INTEGER,
                    percent INTEGER,
                    timestamp TEXT
                )
            ''')
            # Create table for per-topic stats
            cur.execute('''
                CREATE TABLE IF NOT EXISTS topic_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    topic TEXT,
                    correct INTEGER,
                    total INTEGER,
                    timestamp TEXT
                )
            ''')
            # Insert overall quiz score
            cur.execute(
                'INSERT INTO quiz_scores (user_id, score, total, percent, timestamp) VALUES (?, ?, ?, ?, ?)',
                (user_id, score, total, percent,
                 datetime.now(timezone.utc).isoformat())
            )
        else:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS quiz_scores (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    score INTEGER,
                    total INTEGER,
                    percent INTEGER,
                    timestamp TIMESTAMP
                )
            ''')
            # Create table for per-topic stats
            cur.execute('''
                CREATE TABLE IF NOT EXISTS topic_scores (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    topic TEXT,
                    correct INTEGER,
                    total INTEGER,
                    timestamp TIMESTAMP
                )
            ''')
            # Insert overall quiz score
            cur.execute(
                'INSERT INTO quiz_scores (user_id, score, total, percent, timestamp) VALUES (%s, %s, %s, %s, %s)',
                (user_id, score, total, percent, datetime.now(timezone.utc))
            )

        # Insert per-topic stats if provided
        if topic_scores:
            for topic, (correct, total_q) in topic_scores.items():
                if DB_URL.startswith('sqlite'):
                    cur.execute(
                        'INSERT INTO topic_scores (user_id, topic, correct, total, timestamp) VALUES (?, ?, ?, ?, ?)',
                        (user_id, topic, correct, total_q,
                         datetime.now(timezone.utc).isoformat())
                    )
                else:
                    cur.execute(
                        'INSERT INTO topic_scores (user_id, topic, correct, total, timestamp) VALUES (%s, %s, %s, %s, %s)',
                        (user_id, topic, correct, total_q,
                         datetime.now(timezone.utc))
                    )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error - log_quiz_score] {e}")


def get_quiz_stats(user_id):
    """Fetch quiz stats for a user: total quizzes, average score, best score, worst topic"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Query all quiz scores for the user
        query = get_quiz_stats_query()
        cur.execute(query, (user_id,))
        rows = cur.fetchall()

        # Query per-topic stats for the user
        topic_query = get_topic_stats_query()
        cur.execute(topic_query, (user_id,))
        topic_rows = cur.fetchall()

        cur.close()
        conn.close()

        if not rows:
            return 0, 0, 0, 0, 'N/A'

        total_quizzes = len(rows)
        percents = [row[2] for row in rows]
        avg_score = round(sum(percents) / total_quizzes, 2)
        best_score = max(percents)
        worst_score = min(percents)

        # Find worst topic (lowest percent correct)
        worst_topic = 'N/A'
        min_percent = 101
        for topic, correct, total_q in topic_rows:
            if total_q and correct is not None:
                percent = 100 * correct / total_q
                if percent < min_percent:
                    min_percent = percent
                    worst_topic = topic

        return total_quizzes, avg_score, best_score, worst_score, worst_topic
    except Exception as e:
        print(f"[DB Error - get_quiz_stats] {e}")
        return 0, 0, 0, 0, 'N/A'


def get_db_overview():
    """Return lightweight counts for monitoring and health endpoints."""
    tables = ['messages', 'events', 'quiz_attempts',
              'quiz_scores', 'topic_scores']
    counts = {}

    for table in tables:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            counts[table] = cur.fetchone()[0]
            cur.close()
            conn.close()
        except Exception:
            counts[table] = 0

    return counts
