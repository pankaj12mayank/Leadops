import csv
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from backend.config.loader import BASE_DIR
from backend.core.normalizer import NORMALIZED_FIELDS

EXPORTS_DIR = BASE_DIR / "storage" / "exports"
_EXPORT_TTL_DAYS = 7

CSV_INJECTION_CHARS = ("=", "+", "-", "@")
_CSV_INJECTION_WARNED: set[int] = set()


def _sanitize_csv_value(value: Any) -> str:
    s = str(value) if value is not None else ""
    if s and s[0] in CSV_INJECTION_CHARS:
        return "'" + s
    return s


def _sanitize_row(row: list[Any]) -> list[str]:
    return [_sanitize_csv_value(v) for v in row]


def export_job_csv(job_id: int, leads: list[dict[str, Any]], logger: Optional[logging.Logger] = None) -> Optional[Path]:
    if not leads:
        return None

    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    dup_skipped = 0

    for lead in leads:
        website = (lead.get("website") or "").strip().lower()
        phone = (lead.get("phone") or "").strip().lower()
        key = (website, phone)
        if key in seen:
            dup_skipped += 1
            continue
        seen.add(key)
        deduped.append(lead)

    if not deduped:
        return None

    out = EXPORTS_DIR / f"{job_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(NORMALIZED_FIELDS)
            for lead in deduped:
                raw_row = [lead.get(field, "") for field in NORMALIZED_FIELDS]
                writer.writerow(_sanitize_row(raw_row))
    except Exception as e:
        if logger:
            logger.error("CSV export failed for job %d: %s", job_id, e)
        return None

    if logger:
        logger.info(
            "Exported job %d: %d rows (dedup removed %d) → %s",
            job_id, len(deduped), dup_skipped, out,
        )
    return out


def cleanup_expired_exports(logger: Optional[logging.Logger] = None) -> int:
    if not EXPORTS_DIR.exists():
        return 0
    cutoff = time.time() - (_EXPORT_TTL_DAYS * 86400)
    removed = 0
    for f in EXPORTS_DIR.iterdir():
        if f.is_file() and f.suffix == ".csv":
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    if logger and removed:
        logger.info("Cleanup removed %d expired export(s) from %s", removed, EXPORTS_DIR)
    return removed


def get_export_path(job_id: int) -> Path:
    return EXPORTS_DIR / f"{job_id}.csv"


def export_still_valid(job_id: int) -> bool:
    p = get_export_path(job_id)
    if not p.exists():
        return False
    age = time.time() - p.stat().st_mtime
    return age < (_EXPORT_TTL_DAYS * 86400)
