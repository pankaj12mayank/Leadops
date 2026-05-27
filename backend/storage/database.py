import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Generator, Optional

from backend.config.loader import BASE_DIR

DB_DIR = BASE_DIR / "storage"
DB_PATH = DB_DIR / "leadops.db"
_SCHEMA_VERSION = 3


def _get_conn() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextlib.contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    query TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    total_found INTEGER DEFAULT 0,
    preview_generated INTEGER DEFAULT 0,
    payment_status TEXT DEFAULT 'unpaid',
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    progress REAL DEFAULT 0.0,
    current_page INTEGER DEFAULT 0,
    total_pages INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_job_id INTEGER REFERENCES scrape_jobs(id),
    source TEXT NOT NULL,
    business_name TEXT,
    website TEXT,
    phone TEXT,
    email TEXT,
    location TEXT,
    category TEXT,
    rating REAL,
    raw_data TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_job_id INTEGER REFERENCES scrape_jobs(id),
    stripe_session_id TEXT,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'usd',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preview_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_job_id INTEGER UNIQUE REFERENCES scrape_jobs(id),
    viewed_at TEXT,
    downloaded INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status ON scrape_jobs(status);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_source ON scrape_jobs(source);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_created ON scrape_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_leads_job ON leads(scrape_job_id);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);
CREATE INDEX IF NOT EXISTS idx_leads_business ON leads(business_name);
CREATE INDEX IF NOT EXISTS idx_leads_website ON leads(website);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_payments_job ON payments(scrape_job_id);
CREATE INDEX IF NOT EXISTS idx_payments_session ON payments(stripe_session_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_preview_job ON preview_tracking(scrape_job_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_username ON admin_users(username);

CREATE TABLE IF NOT EXISTS preview_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_job_id INTEGER NOT NULL REFERENCES scrape_jobs(id),
    ip_hash TEXT NOT NULL,
    viewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_preview_access_job_ip ON preview_access(scrape_job_id, ip_hash);
CREATE INDEX IF NOT EXISTS idx_preview_access_job ON preview_access(scrape_job_id);
"""


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current_version = row[0] if row[0] is not None else 0

        if current_version < 2:
            try:
                conn.execute("ALTER TABLE scrape_jobs ADD COLUMN retry_count INTEGER DEFAULT 0")
                conn.execute("ALTER TABLE scrape_jobs ADD COLUMN progress REAL DEFAULT 0.0")
                conn.execute("ALTER TABLE scrape_jobs ADD COLUMN current_page INTEGER DEFAULT 0")
                conn.execute("ALTER TABLE scrape_jobs ADD COLUMN total_pages INTEGER DEFAULT 0")
                conn.execute("UPDATE scrape_jobs SET status = 'queued' WHERE status = 'pending'")
            except Exception:
                pass

        if current_version < 3:
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS preview_access (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scrape_job_id INTEGER NOT NULL REFERENCES scrape_jobs(id),
                        ip_hash TEXT NOT NULL,
                        viewed_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_preview_access_job_ip ON preview_access(scrape_job_id, ip_hash)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_preview_access_job ON preview_access(scrape_job_id)")
            except Exception:
                pass

        if current_version < _SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (_SCHEMA_VERSION, _now()),
            )


# ── scrape_jobs ──────────────────────────────────────────────


def create_job(
    source: str,
    query: Optional[str] = None,
    status: str = "queued",
) -> int:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO scrape_jobs (source, query, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (source, query, status, now, now),
        )
        return cur.lastrowid


def update_job(
    job_id: int,
    **kwargs: Any,
) -> None:
    now = _now()
    fields = {k: v for k, v in kwargs.items() if v is not None}
    if not fields:
        return
    fields["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with get_db() as conn:
        conn.execute(f"UPDATE scrape_jobs SET {set_clause} WHERE id = ?", vals)


def get_job(job_id: int) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM scrape_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def update_job_progress(job_id: int, progress: float, current_page: int = 0, total_found: int = 0) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE scrape_jobs SET progress = ?, current_page = ?, total_found = ?, updated_at = ? WHERE id = ?",
            (progress, current_page, total_found, now, job_id),
        )


def increment_job_retry(job_id: int) -> int:
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE scrape_jobs SET retry_count = retry_count + 1, status = 'queued', updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        row = conn.execute("SELECT retry_count FROM scrape_jobs WHERE id = ?", (job_id,)).fetchone()
        return row[0] if row else 0


def get_next_queued_job() -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def mark_stale_jobs(timeout_minutes: int = 30) -> int:
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE scrape_jobs SET status = 'failed', error_message = 'Timeout', updated_at = ? "
            "WHERE status = 'running' AND updated_at < ?",
            (_now(), cutoff),
        )
        return cur.rowcount


def list_jobs(
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with get_db() as conn:
        q = "SELECT * FROM scrape_jobs WHERE 1=1"
        params: list[Any] = []
        if source:
            q += " AND source = ?"
            params.append(source)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(q, params).fetchall()]


# ── leads ────────────────────────────────────────────────────


def insert_lead(
    scrape_job_id: int,
    source: str,
    business_name: Optional[str] = None,
    website: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    location: Optional[str] = None,
    category: Optional[str] = None,
    rating: Optional[float] = None,
    raw_data: Optional[dict[str, Any]] = None,
) -> int:
    now = _now()
    raw_json = json.dumps(raw_data) if raw_data else None
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO leads
               (scrape_job_id, source, business_name, website, phone, email,
                location, category, rating, raw_data, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scrape_job_id, source, business_name, website, phone, email,
             location, category, rating, raw_json, now, now),
        )
        return cur.lastrowid


def get_leads_by_job(job_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM leads WHERE scrape_job_id = ? ORDER BY id", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_leads(
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    with get_db() as conn:
        q = "SELECT * FROM leads WHERE 1=1"
        params: list[Any] = []
        if source:
            q += " AND source = ?"
            params.append(source)
        q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def count_leads(source: Optional[str] = None) -> int:
    with get_db() as conn:
        if source:
            return conn.execute("SELECT COUNT(*) FROM leads WHERE source = ?", (source,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]


# ── payments ─────────────────────────────────────────────────


def create_payment(
    scrape_job_id: int,
    amount: float,
    currency: str = "usd",
    stripe_session_id: Optional[str] = None,
) -> int:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO payments (scrape_job_id, stripe_session_id, amount, currency, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (scrape_job_id, stripe_session_id, amount, currency, now, now),
        )
        return cur.lastrowid


def update_payment(payment_id: int, **kwargs: Any) -> None:
    now = _now()
    fields = {k: v for k, v in kwargs.items() if v is not None}
    if not fields:
        return
    fields["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [payment_id]
    with get_db() as conn:
        conn.execute(f"UPDATE payments SET {set_clause} WHERE id = ?", vals)


def get_payment_by_job(job_id: int) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM payments WHERE scrape_job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_payment_by_session(stripe_session_id: str) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE stripe_session_id = ?", (stripe_session_id,)
        ).fetchone()
        return dict(row) if row else None


def update_job_payment_status(job_id: int, status: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE scrape_jobs SET payment_status = ?, updated_at = ? WHERE id = ?",
            (status, now, job_id),
        )


# ── preview_access (per-IP) ─────────────────────────────────


def get_preview_access(job_id: int, ip_hash: str) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM preview_access WHERE scrape_job_id = ? AND ip_hash = ?",
            (job_id, ip_hash),
        ).fetchone()
        return dict(row) if row else None


def grant_preview_access(job_id: int, ip_hash: str) -> bool:
    now = _now()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO preview_access (scrape_job_id, ip_hash, viewed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, ip_hash, now, now, now),
            )
        return True
    except Exception:
        return False


# ── admin_users ──────────────────────────────────────────────


def create_admin_user(username: str, password_hash: str) -> int:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO admin_users (username, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, now, now),
        )
        return cur.lastrowid


def get_admin_user(username: str) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def update_admin_password(username: str, password_hash: str) -> bool:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE admin_users SET password_hash = ?, updated_at = ? WHERE username = ?",
            (password_hash, now, username),
        )
        return cur.rowcount > 0


SOURCE_TO_CONTENT_DIR = {
    "clutch": "agency",
    "goodfirms": "agency",
    "maps": "local",
    "linkedin": "startup",
}


def _map_row_to_lead(source: str, raw: dict, columns: list) -> dict:
    base = {"source": source, "raw_data": raw}
    col_lower = {c.lower(): c for c in columns}
    if source in ("clutch", "goodfirms"):
        base["business_name"] = raw.get(col_lower.get("company_name", ""), "")
        base["website"] = raw.get(col_lower.get("website", ""), "")
        base["location"] = raw.get(col_lower.get("location", ""), "")
        r = raw.get(col_lower.get("rating", ""), "")
        try:
            base["rating"] = float(r) if r else None
        except (ValueError, TypeError):
            base["rating"] = None
    elif source == "maps":
        base["business_name"] = raw.get(col_lower.get("business_name", ""), "")
        base["website"] = raw.get(col_lower.get("website", ""), "")
        base["phone"] = raw.get(col_lower.get("phone", ""), "")
        base["location"] = raw.get(col_lower.get("address", ""), "")
        base["category"] = raw.get(col_lower.get("category", ""), "")
        r = raw.get(col_lower.get("rating", ""), "")
        try:
            base["rating"] = float(r) if r else None
        except (ValueError, TypeError):
            base["rating"] = None
    elif source == "linkedin":
        base["business_name"] = raw.get(
            col_lower.get("matched_company_name", ""),
            raw.get(col_lower.get("input_company_name", ""), ""),
        )
        base["website"] = raw.get(col_lower.get("input_website", ""), "")
    return base


def import_csv_to_db(source: str, job_id: int, logger: Any = None) -> int:
    import logging
    log = logger or logging.getLogger(__name__)
    subdir = SOURCE_TO_CONTENT_DIR.get(source)
    if not subdir:
        return 0
    export_dir = BASE_DIR / "content" / subdir
    if not export_dir.exists():
        return 0
    csv_files = sorted(export_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csv_files:
        return 0
    latest = csv_files[0]
    try:
        import pandas as pd
        df = pd.read_csv(latest, encoding="utf-8-sig", low_memory=False)
    except Exception as e:
        log.warning("Failed to read CSV %s for DB import: %s", latest.name, e)
        return 0
    df.columns = [c.strip().lower() for c in df.columns]
    imported = 0
    for _, row in df.iterrows():
        raw = {k: v for k, v in row.items() if pd.notna(v)}
        lead = _map_row_to_lead(source, raw, df.columns)
        lead["scrape_job_id"] = job_id
        insert_lead(**lead)
        imported += 1
    log.info("Imported %d leads from %s into DB (job %d)", imported, latest.name, job_id)
    return imported
