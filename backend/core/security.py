import hashlib
import logging
import time
from typing import Optional

from fastapi import HTTPException

from backend.storage.database import get_db

_logger = logging.getLogger("security")

VALID_SOURCES = frozenset({"clutch", "goodfirms", "maps", "linkedin"})
MAX_PAGES_LIMIT = 20
_RATE_LIMIT_WINDOW = 3600
_RATE_LIMIT_MAX = 3


def validate_source(source: str) -> str:
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source: '{source}'. Must be one of: {', '.join(sorted(VALID_SOURCES))}")
    return source


def validate_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="Query too long (max 500 characters)")
    return q


def validate_max_pages(max_pages: int) -> int:
    if max_pages < 1:
        raise HTTPException(status_code=400, detail="max_pages must be at least 1")
    if max_pages > MAX_PAGES_LIMIT:
        raise HTTPException(status_code=400, detail=f"max_pages cannot exceed {MAX_PAGES_LIMIT}")
    return max_pages


def hash_ip(client_ip: str) -> str:
    return hashlib.sha256(client_ip.encode()).hexdigest()


def _ensure_rate_table() -> None:
    with get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS rate_limits ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  ip_hash TEXT NOT NULL,"
            "  endpoint TEXT NOT NULL,"
            "  created_at REAL NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rate_limits_lookup ON rate_limits(ip_hash, endpoint, created_at)"
        )


def check_rate_limit(ip_hash: str, endpoint: str = "scrape") -> None:
    _ensure_rate_table()
    cutoff = time.time() - _RATE_LIMIT_WINDOW
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE ip_hash = ? AND endpoint = ? AND created_at > ?",
            (ip_hash, endpoint, cutoff),
        ).fetchone()[0]
    if count >= _RATE_LIMIT_MAX:
        _logger.warning("Rate limit hit for ip_hash=%s (%s): %d in window", ip_hash[:12], endpoint, count)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {_RATE_LIMIT_MAX} requests per hour per IP",
        )
    with get_db() as conn:
        conn.execute(
            "INSERT INTO rate_limits (ip_hash, endpoint, created_at) VALUES (?, ?, ?)",
            (ip_hash, endpoint, time.time()),
        )


def prune_rate_limits() -> None:
    _ensure_rate_table()
    cutoff = time.time() - _RATE_LIMIT_WINDOW
    with get_db() as conn:
        cur = conn.execute("DELETE FROM rate_limits WHERE created_at < ?", (cutoff,))
        if cur.rowcount > 0:
            _logger.debug("Pruned %d expired rate limit records", cur.rowcount)
