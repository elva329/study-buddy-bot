import os
import configparser
from datetime import datetime
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config', 'config.ini'))


def get_db_url():
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        return db_url
    if 'database' in config and 'url' in config['database']:
        return config['database']['url']
    return 'sqlite:///studybuddy.db'


DB_URL = get_db_url()

# Determine DB type
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


def log_message(user_id, message, sender):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(CREATE_TABLE)
        cur.execute(INSERT, (user_id, message, sender, datetime.utcnow(
        ).isoformat() if DB_URL.startswith('sqlite') else datetime.utcnow()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error] {e}")
