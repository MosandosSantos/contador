import os
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor

@contextmanager
def connection():
    conn = psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=5)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def fetch(sql, params=()):
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

def execute(sql, params=()):
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
