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
        ensure_user_exists(conn, user_id)
        cur = conn.cursor()

        ensure_core_schema(conn)

        quiz_id = create_quiz_record(
            conn, 'Generated Quiz', 'Study Materials', num_questions)

        # Insert a started quiz attempt; score will be filled in on completion.
        insert_quiz_attempt(
            conn,
            user_id=user_id,
            quiz_id=quiz_id,
            num_questions=num_questions,
            score=None,
            percent=None,
            passed=None,
            weak_topic=None,
            topic_breakdown=None,
            status='started'
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
        conn = sqlite3.connect(db_path)
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    CREATE_TABLE = '''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            sender_type TEXT,
            timestamp TEXT
        )
    '''
    INSERT = 'INSERT INTO messages (user_id, content, sender_type, timestamp) VALUES (?, ?, ?, ?)'

    # SQLite-specific query helpers
    def get_quiz_history_query():
        return 'SELECT timestamp, num_questions FROM quiz_attempts WHERE user_id = ? AND score IS NOT NULL ORDER BY timestamp DESC LIMIT ?'

    def get_quiz_stats_query():
        return 'SELECT score, num_questions, percent, weak_topic, topic_breakdown FROM quiz_attempts WHERE user_id = ? AND score IS NOT NULL'

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
            content TEXT,
            sender_type VARCHAR(10),
            timestamp TIMESTAMP
        )
    '''
    INSERT = 'INSERT INTO messages (user_id, content, sender_type, timestamp) VALUES (%s, %s, %s, %s)'

    # PostgreSQL-specific query helpers
    def get_quiz_history_query():
        return 'SELECT timestamp, num_questions FROM quiz_attempts WHERE user_id = %s AND score IS NOT NULL ORDER BY timestamp DESC LIMIT %s'

    def get_quiz_stats_query():
        return 'SELECT score, num_questions, percent, weak_topic, topic_breakdown FROM quiz_attempts WHERE user_id = %s AND score IS NOT NULL'

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


def ensure_core_schema(conn):
    cur = conn.cursor()

    if DB_URL.startswith('sqlite'):
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                email TEXT,
                first_seen_at TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                total_questions INTEGER NOT NULL CHECK (total_questions > 0),
                created_at TEXT NOT NULL
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                quiz_id INTEGER NOT NULL,
                num_questions INTEGER NOT NULL CHECK (num_questions > 0),
                score INTEGER,
                percent INTEGER,
                passed INTEGER,
                weak_topic TEXT,
                topic_breakdown TEXT,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                sender_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()
        cur.close()
        ensure_column_exists(conn, 'users', 'username', 'TEXT')
        ensure_column_exists(conn, 'users', 'email', 'TEXT')
        ensure_column_exists(conn, 'users', 'first_seen_at', 'TEXT')
        ensure_column_exists(conn, 'quizzes', 'title', 'TEXT')
        ensure_column_exists(conn, 'quizzes', 'category', 'TEXT')
        ensure_column_exists(conn, 'quizzes', 'total_questions', 'INTEGER')
        ensure_column_exists(conn, 'quizzes', 'created_at', 'TEXT')
        ensure_column_exists(conn, 'quiz_attempts', 'quiz_id', 'INTEGER')
        ensure_column_exists(conn, 'quiz_attempts', 'num_questions', 'INTEGER')
        ensure_column_exists(conn, 'quiz_attempts', 'score', 'INTEGER')
        ensure_column_exists(conn, 'quiz_attempts', 'percent', 'INTEGER')
        ensure_column_exists(conn, 'quiz_attempts', 'passed', 'INTEGER')
        ensure_column_exists(conn, 'quiz_attempts', 'weak_topic', 'TEXT')
        ensure_column_exists(conn, 'quiz_attempts', 'topic_breakdown', 'TEXT')
        ensure_column_exists(conn, 'quiz_attempts', 'status', 'TEXT')
        ensure_column_exists(conn, 'messages', 'content', 'TEXT')
        ensure_column_exists(conn, 'messages', 'sender_type', 'TEXT')
        ensure_column_exists(conn, 'messages', 'timestamp', 'TEXT')
        ensure_column_exists(conn, 'events', 'event_type', 'TEXT')
        ensure_column_exists(conn, 'events', 'payload', 'TEXT')
        ensure_column_exists(conn, 'events', 'timestamp', 'TEXT')
        ensure_indexes(conn)
        return

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            email TEXT,
            first_seen_at TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS quizzes (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            total_questions INTEGER NOT NULL CHECK (total_questions > 0),
            created_at TIMESTAMP NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
            num_questions INTEGER NOT NULL CHECK (num_questions > 0),
            score INTEGER,
            percent INTEGER,
            passed INTEGER,
            weak_topic TEXT,
            topic_breakdown TEXT,
            status VARCHAR(32) NOT NULL,
            timestamp TIMESTAMP NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            sender_type VARCHAR(10) NOT NULL,
            timestamp TIMESTAMP NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_type VARCHAR(64) NOT NULL,
            payload TEXT,
            timestamp TIMESTAMP NOT NULL
        )
    ''')
    conn.commit()
    cur.close()
    ensure_column_exists(conn, 'users', 'username', 'TEXT')
    ensure_column_exists(conn, 'users', 'email', 'TEXT')
    ensure_column_exists(conn, 'users', 'first_seen_at', 'TIMESTAMP')
    ensure_column_exists(conn, 'quizzes', 'title', 'TEXT')
    ensure_column_exists(conn, 'quizzes', 'category', 'TEXT')
    ensure_column_exists(conn, 'quizzes', 'total_questions', 'INTEGER')
    ensure_column_exists(conn, 'quizzes', 'created_at', 'TIMESTAMP')
    ensure_column_exists(conn, 'quiz_attempts', 'quiz_id', 'INTEGER')
    ensure_column_exists(conn, 'quiz_attempts', 'num_questions', 'INTEGER')
    ensure_column_exists(conn, 'quiz_attempts', 'score', 'INTEGER')
    ensure_column_exists(conn, 'quiz_attempts', 'percent', 'INTEGER')
    ensure_column_exists(conn, 'quiz_attempts', 'passed', 'INTEGER')
    ensure_column_exists(conn, 'quiz_attempts', 'weak_topic', 'TEXT')
    ensure_column_exists(conn, 'quiz_attempts', 'topic_breakdown', 'TEXT')
    ensure_column_exists(conn, 'quiz_attempts', 'status', 'VARCHAR(32)')
    ensure_indexes(conn)


def ensure_indexes(conn):
    cur = conn.cursor()
    index_statements = [
        'CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user_timestamp ON quiz_attempts (user_id, timestamp DESC)',
        'CREATE INDEX IF NOT EXISTS idx_quiz_attempts_quiz_id ON quiz_attempts (quiz_id)',
        'CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user_status_timestamp ON quiz_attempts (user_id, status, timestamp DESC)',
        'CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp ON messages (user_id, timestamp DESC)',
        'CREATE INDEX IF NOT EXISTS idx_events_user_timestamp ON events (user_id, timestamp DESC)',
    ]
    for statement in index_statements:
        cur.execute(statement)
    conn.commit()
    cur.close()


def ensure_user_exists(conn, user_id, username=None, email=None):
    ensure_core_schema(conn)
    cur = conn.cursor()
    username = username or f'telegram_{user_id}'

    if DB_URL.startswith('sqlite'):
        cur.execute(
            'INSERT OR IGNORE INTO users (id, username, email, first_seen_at) VALUES (?, ?, ?, ?)',
            (user_id, username, email, get_current_timestamp())
        )
    else:
        cur.execute(
            'INSERT INTO users (id, username, email, first_seen_at) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING',
            (user_id, username, email, get_current_timestamp())
        )

    conn.commit()
    cur.close()


def create_quiz_record(conn, title, category, total_questions):
    ensure_core_schema(conn)
    cur = conn.cursor()

    if DB_URL.startswith('sqlite'):
        cur.execute(
            'INSERT INTO quizzes (title, category, total_questions, created_at) VALUES (?, ?, ?, ?)',
            (title, category, total_questions, get_current_timestamp())
        )
        quiz_id = cur.lastrowid
    else:
        cur.execute(
            'INSERT INTO quizzes (title, category, total_questions, created_at) VALUES (%s, %s, %s, %s) RETURNING id',
            (title, category, total_questions, get_current_timestamp())
        )
        quiz_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    return quiz_id


def insert_quiz_attempt(conn, user_id, quiz_id, num_questions, score=None, percent=None, passed=None,
                        weak_topic=None, topic_breakdown=None, status='started'):
    ensure_core_schema(conn)
    cur = conn.cursor()

    if DB_URL.startswith('sqlite'):
        cur.execute(
            'INSERT INTO quiz_attempts (user_id, quiz_id, num_questions, score, percent, passed, weak_topic, topic_breakdown, status, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (user_id, quiz_id, num_questions, score, percent, passed,
             weak_topic, topic_breakdown, status, get_current_timestamp())
        )
        attempt_id = cur.lastrowid
    else:
        cur.execute(
            'INSERT INTO quiz_attempts (user_id, quiz_id, num_questions, score, percent, passed, weak_topic, topic_breakdown, status, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id',
            (user_id, quiz_id, num_questions, score, percent, passed,
             weak_topic, topic_breakdown, status, get_current_timestamp())
        )
        attempt_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    return attempt_id


def update_latest_quiz_attempt(conn, user_id, score, total, percent, passed, weak_topic, topic_breakdown):
    ensure_core_schema(conn)
    cur = conn.cursor()
    status = 'passed' if passed else 'failed'

    if DB_URL.startswith('sqlite'):
        cur.execute(
            'SELECT id FROM quiz_attempts WHERE user_id = ? AND status = ? ORDER BY timestamp DESC LIMIT 1',
            (user_id, 'started')
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                'UPDATE quiz_attempts SET score = ?, percent = ?, passed = ?, weak_topic = ?, topic_breakdown = ?, status = ?, timestamp = ? WHERE id = ?',
                (score, percent, passed, weak_topic, topic_breakdown,
                 status, get_current_timestamp(), row[0])
            )
            conn.commit()
            cur.close()
            return True
    else:
        cur.execute(
            'SELECT id FROM quiz_attempts WHERE user_id = %s AND status = %s ORDER BY timestamp DESC LIMIT 1',
            (user_id, 'started')
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                'UPDATE quiz_attempts SET score = %s, percent = %s, passed = %s, weak_topic = %s, topic_breakdown = %s, status = %s, timestamp = %s WHERE id = %s',
                (score, percent, passed, weak_topic, topic_breakdown,
                 status, get_current_timestamp(), row[0])
            )
            conn.commit()
            cur.close()
            return True

    cur.close()
    return False


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
        ensure_user_exists(conn, user_id)
        cur = conn.cursor()
        ensure_core_schema(conn)
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
        ensure_user_exists(conn, user_id)
        cur = conn.cursor()

        payload_text = json.dumps(
            payload, ensure_ascii=False) if payload is not None else None

        ensure_core_schema(conn)

        if DB_URL.startswith('sqlite'):
            cur.execute(
                'INSERT INTO events (user_id, event_type, payload, timestamp) VALUES (?, ?, ?, ?)',
                (user_id, event_type, payload_text,
                 datetime.now(timezone.utc).isoformat())
            )
        else:
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
        ensure_user_exists(conn, user_id)
        cur = conn.cursor()

        ensure_core_schema(conn)

        passed = calculate_passed(score, total)
        topic_breakdown = serialize_topic_breakdown(topic_scores)
        weak_topic = extract_weak_topic_from_breakdown(topic_breakdown)

        saved = update_latest_quiz_attempt(
            conn, user_id, score, total, percent, passed, weak_topic, topic_breakdown)
        if not saved:
            quiz_id = create_quiz_record(
                conn, 'Generated Quiz', 'Study Materials', total)
            insert_quiz_attempt(
                conn, user_id, quiz_id, total, score, percent, passed,
                weak_topic, topic_breakdown, status='passed' if passed else 'failed'
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
    tables = ['users', 'quizzes', 'messages', 'events', 'quiz_attempts']
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
