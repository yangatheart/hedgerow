"""Persistence. Schema follows PRD section 8 (related tables, nullable unknowns).

PostgreSQL when DATABASE_URL is set (production on Render); SQLite otherwise (zero-setup local dev).
Queries are written once with `?` placeholders; the Postgres adapter translates them.
"""
import os
import re
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
DB_PATH = os.environ.get("AGRI_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "agri.db"))

# Shared table definitions; {pk} is the auto-increment primary key for each dialect.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id {pk},
    email TEXT UNIQUE,
    password_hash TEXT,
    preferred_language TEXT DEFAULT 'en',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS farms (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    location_label TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    timezone TEXT,
    size_category TEXT,
    area_value DOUBLE PRECISION,
    area_unit TEXT,
    production_types TEXT DEFAULT '[]',
    main_concern TEXT,
    onboarding_step INTEGER DEFAULT 1,
    status TEXT DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS production_items (
    id {pk},
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    area_or_count DOUBLE PRECISION,
    unit TEXT,
    planting_date TEXT,
    growth_stage TEXT
);
CREATE TABLE IF NOT EXISTS farm_conditions (
    farm_id INTEGER PRIMARY KEY REFERENCES farms(id) ON DELETE CASCADE,
    water_access TEXT,
    irrigation_type TEXT,
    soil_type TEXT,
    drainage TEXT,
    waterlogging_history TEXT,
    soil_moisture_observation TEXT
);
CREATE TABLE IF NOT EXISTS weather_snapshots (
    id {pk},
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    fetched_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_assessments (
    id {pk},
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    hazard TEXT NOT NULL,
    title TEXT NOT NULL,
    level TEXT NOT NULL,
    priority_score INTEGER,
    applies_to TEXT,
    window_start TEXT,
    window_end TEXT,
    evidence TEXT,
    caveats TEXT,
    missing_inputs TEXT,
    weather_snapshot_id INTEGER,
    model_version TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    valid_until TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendations (
    id {pk},
    assessment_id INTEGER NOT NULL REFERENCES risk_assessments(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    rationale TEXT,
    urgency TEXT,
    applicability TEXT,
    caveat TEXT,
    valid_until TEXT,
    status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS feedback (
    id {pk},
    recommendation_id INTEGER NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
    useful INTEGER,
    action_taken INTEGER,
    outcome_notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_farms_user ON farms(user_id);
CREATE INDEX IF NOT EXISTS ix_assess_farm ON risk_assessments(farm_id, assessed_at);
CREATE INDEX IF NOT EXISTS ix_weather_farm ON weather_snapshots(farm_id, fetched_at);
CREATE INDEX IF NOT EXISTS ix_recs_assessment ON recommendations(assessment_id);
CREATE INDEX IF NOT EXISTS ix_feedback_rec ON feedback(recommendation_id);
"""

# Tables whose primary key is not `id` (no RETURNING id on insert).
_NO_ID_TABLES = {"farm_conditions", "sessions"}
_INSERT_RE = re.compile(r"^\s*INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+(\w+)", re.I)


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid = cur, lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur.fetchall())


class _PgConn:
    """Minimal sqlite3-style facade over psycopg (execute with ?, lastrowid, dict rows)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        m = _INSERT_RE.match(sql)
        ignore = re.search(r"INSERT\s+OR\s+IGNORE", sql, re.I) is not None
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.I).replace("?", "%s")
        returning = bool(m) and m.group(1).lower() not in _NO_ID_TABLES and "RETURNING" not in sql.upper()
        if ignore:
            sql += " ON CONFLICT DO NOTHING"
        if returning:
            sql += " RETURNING id"
        cur = self._conn.execute(sql, params)
        lastrowid = None
        if returning:
            row = cur.fetchone()
            lastrowid = row["id"] if row else None
        return _PgCursor(cur, lastrowid)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def connect():
    if IS_PG:
        import psycopg
        from psycopg.rows import dict_row
        return _PgConn(psycopg.connect(DATABASE_URL, row_factory=dict_row))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    if IS_PG:
        conn = connect()
        try:
            for stmt in SCHEMA.format(pk="SERIAL PRIMARY KEY").split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            conn.commit()
        finally:
            conn.close()
        return
    # Local databases from before accounts existed: keep a backup and start fresh.
    if os.path.exists(DB_PATH):
        probe = sqlite3.connect(DB_PATH)
        cols = {r[1] for r in probe.execute("PRAGMA table_info(users)")}
        probe.close()
        if cols and ("email" not in cols or "token_hash" in cols):
            os.replace(DB_PATH, DB_PATH + ".pre-accounts.bak")
    conn = connect()
    try:
        conn.executescript(SCHEMA.format(pk="INTEGER PRIMARY KEY AUTOINCREMENT"))
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
