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
REQUIRE_CLOUD_DB = os.getenv('REQUIRE_CLOUD_DB', 'false').lower() in (
    '1', 'true', 'yes', 'on')
PASS_PERCENT_THRESHOLD = int(os.getenv('PASS_PERCENT_THRESHOLD', '60'))

if REQUIRE_CLOUD_DB and DB_URL.startswith('sqlite'):
    raise RuntimeError(
        'REQUIRE_CLOUD_DB is enabled but DB configuration resolved to sqlite. '
        'Set DATABASE_URL or DB_HOST/DB_USER/DB_PASSWORD/DB_NAME for PostgreSQL.'
    )

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
        return 'SELECT score, total, percent, weak_topic, topic_breakdown FROM quiz_scores WHERE user_id = ?'

    def get_current_timestamp():
        return datetime.now(timezone.utc).isoformat()

    def ensure_column_exists(conn, table_name, column_name, column_type):
        cur = conn.cursor()
        cur.execute(f'PRAGMA table_info({table_name})')
        existing_columns = {row[1] for row in cur.fetchall()}
        if column_name not in existing_columns:
            cur.execute(
                f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}'
            )
            conn.commit()
        cur.close()

else:
    def get_conn():
        import psycopg2
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
        return 'SELECT score, total, percent, weak_topic, topic_breakdown FROM quiz_scores WHERE user_id = %s'

    def get_current_timestamp():
        return datetime.now(timezone.utc)

    def ensure_column_exists(conn, table_name, column_name, column_type):
        cur = conn.cursor()
        cur.execute(
            '''
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            ''',
            (table_name, column_name)
        )
        if cur.fetchone() is None:
            cur.execute(
                f'ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}'
            )
            conn.commit()
        cur.close()


def ensure_quiz_schema(conn):
    cur = conn.cursor()

    if DB_URL.startswith('sqlite'):
        cur.execute('''
            CREATE TABLE IF NOT EXISTS quiz_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                score INTEGER,
                total INTEGER,
                percent INTEGER,
                passed INTEGER,
                weak_topic TEXT,
                topic_breakdown TEXT,
                timestamp TEXT
            )
        ''')
        conn.commit()
        cur.close()
        ensure_column_exists(conn, 'quiz_scores', 'passed', 'INTEGER')
        ensure_column_exists(conn, 'quiz_scores', 'weak_topic', 'TEXT')
        ensure_column_exists(conn, 'quiz_scores', 'topic_breakdown', 'TEXT')
        return

    cur.execute('''
        CREATE TABLE IF NOT EXISTS quiz_scores (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            score INTEGER,
            total INTEGER,
            percent INTEGER,
            passed INTEGER,
            weak_topic TEXT,
            topic_breakdown TEXT,
            timestamp TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    ensure_column_exists(conn, 'quiz_scores', 'passed', 'INTEGER')
    ensure_column_exists(conn, 'quiz_scores', 'weak_topic', 'TEXT')
    ensure_column_exists(conn, 'quiz_scores', 'topic_breakdown', 'TEXT')


def normalize_topic_scores(topic_scores):
    if not topic_scores:
        return None

    normalized = {}
    for topic, value in topic_scores.items():
        if isinstance(value, dict):
            correct = int(value.get('correct', 0) or 0)
            total = int(value.get('total', 0) or 0)
        else:
            correct, total = value
            correct = int(correct or 0)
            total = int(total or 0)

        normalized[topic] = {
            'correct': correct,
            'total': total,
            'passed': calculate_passed(correct, total),
        }

    return normalized


def serialize_topic_breakdown(topic_scores):
    normalized = normalize_topic_scores(topic_scores)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


def extract_weak_topic_from_breakdown(topic_breakdown):
    if not topic_breakdown:
        return 'N/A'

    if isinstance(topic_breakdown, str):
        try:
            topic_breakdown = json.loads(topic_breakdown)
        except json.JSONDecodeError:
            return 'N/A'

    worst_topic = 'N/A'
    min_percent = 101

    for topic, value in topic_breakdown.items():
        if isinstance(value, dict):
            correct = value.get('correct', 0)
            total = value.get('total', 0)
        else:
            correct, total = value

        if total:
            percent = 100 * int(correct) / int(total)
            if percent < min_percent:
                min_percent = percent
                worst_topic = topic

    return worst_topic


def calculate_passed(score, total, threshold=PASS_PERCENT_THRESHOLD):
    if total <= 0:
        return 0
    percent = (100 * score) / total
    return 1 if percent >= threshold else 0


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

        ensure_quiz_schema(conn)

        passed = calculate_passed(score, total)
        topic_breakdown = serialize_topic_breakdown(topic_scores)
        weak_topic = extract_weak_topic_from_breakdown(topic_breakdown)

        # Insert overall quiz score including pass/fail outcome
        if DB_URL.startswith('sqlite'):
            cur.execute(
                'INSERT INTO quiz_scores (user_id, score, total, percent, passed, weak_topic, topic_breakdown, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (user_id, score, total, percent, passed, weak_topic, topic_breakdown,
                 datetime.now(timezone.utc).isoformat())
            )
        else:
            cur.execute(
                'INSERT INTO quiz_scores (user_id, score, total, percent, passed, weak_topic, topic_breakdown, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
                (user_id, score, total, percent, passed, weak_topic,
                 topic_breakdown, datetime.now(timezone.utc))
            )

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB Error - log_quiz_score] {e}")
        return False


def get_quiz_stats(user_id):
    """Fetch quiz stats for a user: total quizzes, average score, best score, worst topic"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Query all quiz scores for the user
        query = get_quiz_stats_query()
        cur.execute(query, (user_id,))
        rows = cur.fetchall()

        cur.close()
        conn.close()

        if not rows:
            return 0, 0, 0, 0, 'N/A'

        total_quizzes = len(rows)
        percents = [row[2] for row in rows]
        avg_score = round(sum(percents) / total_quizzes, 2)
        best_score = max(percents)
        worst_score = min(percents)

        topic_totals = {}
        fallback_weak_topics = []

        for row in rows:
            weak_topic = row[3] if len(row) > 3 else None
            topic_breakdown = row[4] if len(row) > 4 else None

            if weak_topic and weak_topic != 'N/A':
                fallback_weak_topics.append(weak_topic)

            if not topic_breakdown:
                continue

            if isinstance(topic_breakdown, str):
                try:
                    topic_breakdown = json.loads(topic_breakdown)
                except json.JSONDecodeError:
                    continue

            for topic, value in topic_breakdown.items():
                if isinstance(value, dict):
                    correct = int(value.get('correct', 0) or 0)
                    total_q = int(value.get('total', 0) or 0)
                else:
                    correct, total_q = value
                    correct = int(correct or 0)
                    total_q = int(total_q or 0)

                if topic not in topic_totals:
                    topic_totals[topic] = {'correct': 0, 'total': 0}
                topic_totals[topic]['correct'] += correct
                topic_totals[topic]['total'] += total_q

        worst_topic = 'N/A'
        min_percent = 101
        for topic, totals in topic_totals.items():
            if totals['total']:
                percent = 100 * totals['correct'] / totals['total']
                if percent < min_percent:
                    min_percent = percent
                    worst_topic = topic

        if worst_topic == 'N/A' and fallback_weak_topics:
            worst_topic = fallback_weak_topics[-1]

        return total_quizzes, avg_score, best_score, worst_score, worst_topic
    except Exception as e:
        print(f"[DB Error - get_quiz_stats] {e}")
        return 0, 0, 0, 0, 'N/A'


def get_db_overview():
    """Return lightweight counts for monitoring and health endpoints."""
    tables = ['messages', 'events', 'quiz_attempts', 'quiz_scores']
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
