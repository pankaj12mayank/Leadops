import csv
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent

NORMALIZED_COLUMNS = [
    "company_name",
    "website",
    "phone",
    "email",
    "linkedin",
    "location",
    "source_platform",
]


_EXPORT_BASE: Path | None = None


def _get_export_base() -> Path:
    global _EXPORT_BASE
    if _EXPORT_BASE is None:
        try:
            cfg_path = BASE_DIR / "config.json"
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                exports_rel = cfg.get("paths", {}).get("exports", "exports")
                _EXPORT_BASE = (BASE_DIR / exports_rel).resolve()
            else:
                _EXPORT_BASE = BASE_DIR / "exports"
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
            _EXPORT_BASE = BASE_DIR / "exports"
    return _EXPORT_BASE


def _get_source_dirs() -> dict[str, Path]:
    eb = _get_export_base()
    return {
        "clutch": eb / "clutch",
        "goodfirms": eb / "goodfirms",
        "maps": eb / "maps",
        "linkedin": eb / "linkedin",
    }

COLUMN_MAP = {
    "clutch": {
        "company_name": "company_name",
        "website": "website",
        "clutch_profile_url": None,
        "location": "location",
        "employee_size": None,
        "hourly_rate": None,
        "services": None,
        "rating": None,
        "source": "source_platform",
        "scraped_at": None,
    },
    "goodfirms": {
        "company_name": "company_name",
        "website": "website",
        "goodfirms_profile_url": None,
        "location": "location",
        "employee_size": None,
        "hourly_rate": None,
        "services": None,
        "rating": None,
        "source": "source_platform",
        "scraped_at": None,
    },
    "maps": {
        "business_name": "company_name",
        "website": "website",
        "phone": "phone",
        "address": "location",
        "rating": None,
        "reviews_count": None,
        "category": None,
        "source": "source_platform",
        "scraped_at": None,
    },
    "linkedin": {
        "input_company_name": "company_name",
        "input_website": "website",
        "linkedin_company_url": "linkedin",
        "founder_name": None,
        "founder_role": None,
        "company_size_from_linkedin": None,
        "matched_company_name": None,
        "enrichment_status": None,
        "enriched_at": None,
    },
}

_logger: logging.Logger | None = None


def _set_logger(logger: logging.Logger) -> None:
    global _logger
    _logger = logger


def _normalize_website(url: Any) -> str:
    if not url or pd.isna(url):
        return ""
    url = str(url).strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = url.rstrip("/")
    return url


def _normalize_phone(phone: Any) -> str:
    if not phone or pd.isna(phone):
        return ""
    return re.sub(r"[^\d+]", "", str(phone).strip())


def _normalize_name(name: Any) -> str:
    if not name or pd.isna(name):
        return ""
    return re.sub(r"\s+", " ", str(name).strip().lower())


_CHUNK_SIZE = 5000


def _read_csv_safe(path: Path, chunked: bool = False) -> pd.DataFrame | None:
    if not chunked:
        for attempt in range(3):
            try:
                if attempt == 0:
                    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
                elif attempt == 1:
                    df = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip", low_memory=False)
                else:
                    raw_rows = []
                    with open(path, encoding="utf-8-sig", errors="replace") as f:
                        reader = csv.reader(f)
                        header = next(reader, None)
                        if header is None:
                            return None
                        header = [h.strip() for h in header]
                        for row in reader:
                            if len(row) == len(header):
                                raw_rows.append(row)
                    if not raw_rows:
                        return None
                    df = pd.DataFrame(raw_rows, columns=header)
                df.columns = [c.strip().lower() for c in df.columns]
                _logger.info("Read %d rows from %s (attempt %d)", len(df), path.name, attempt + 1)
                return df
            except Exception as e:
                _logger.warning("CSV read attempt %d failed for %s: %s", attempt + 1, path.name, e)
        _logger.error("Failed to read CSV after 3 attempts: %s", path.name)
        return None

    chunks: list[pd.DataFrame] = []
    for attempt in range(3):
        try:
            reader = pd.read_csv(
                path, encoding="utf-8-sig",
                chunksize=_CHUNK_SIZE, on_bad_lines="skip", low_memory=False,
            )
            for c in reader:
                c.columns = [col.strip().lower() for col in c.columns]
                chunks.append(c)
            if not chunks:
                return None
            result = pd.concat(chunks, ignore_index=True)
            _logger.info("Read %d rows (chunked) from %s", len(result), path.name)
            return result
        except Exception as e:
            _logger.warning("Chunked CSV read attempt %d failed for %s: %s", attempt + 1, path.name, e)
    _logger.error("Failed to read CSV after 3 chunked attempts: %s", path.name)
    return None


def _map_to_normalized(df: pd.DataFrame, source_key: str) -> pd.DataFrame:
    mapping = COLUMN_MAP[source_key]
    rows = []
    used_map = {}

    missing = [src for src in mapping if src not in df.columns]
    if missing and _logger:
        _logger.warning("Source '%s' missing expected columns: %s", source_key, missing)

    for src_col, tgt_col in mapping.items():
        if tgt_col is not None and src_col in df.columns:
            if tgt_col not in used_map:
                used_map[tgt_col] = src_col
            elif tgt_col == "company_name" and source_key == "linkedin":
                if src_col == "matched_company_name":
                    used_map[tgt_col] = src_col

    for _, row in df.iterrows():
        record = {col: "" for col in NORMALIZED_COLUMNS}
        for tgt_col, src_col in used_map.items():
            val = row.get(src_col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                record[tgt_col] = str(val).strip()
            else:
                record[tgt_col] = ""

        if source_key == "linkedin":
            if record["source_platform"] == "":
                record["source_platform"] = "linkedin"
            if record["company_name"]:
                linkedin_match = row.get("matched_company_name")
                if linkedin_match and not (isinstance(linkedin_match, float) and pd.isna(linkedin_match)):
                    record["company_name"] = str(linkedin_match).strip()

        if source_key == "maps":
            if not record["company_name"] and "business_name" in df.columns:
                bn = row.get("business_name")
                if bn is not None and not (isinstance(bn, float) and pd.isna(bn)):
                    record["company_name"] = str(bn).strip()

        rows.append(record)

    result = pd.DataFrame(rows, columns=NORMALIZED_COLUMNS)
    _logger.info("Mapped %d rows for source '%s'", len(result), source_key)
    return result


def _filter_invalid_rows(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)

    for col in NORMALIZED_COLUMNS:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["_name_ok"] = df["company_name"].str.len() >= 1
    df["_website_ok"] = df["website"].str.len() >= 3
    df["_phone_ok"] = df["phone"].str.len() >= 4
    df["_has_data"] = df["_name_ok"] | df["_website_ok"] | df["_phone_ok"]

    valid = df[df["_has_data"]].copy()
    valid = valid.drop(columns=["_name_ok", "_website_ok", "_phone_ok", "_has_data"])

    after = len(valid)
    removed = before - after
    if removed > 0:
        _logger.warning("Removed %d invalid rows with no identifiable data", removed)
    return valid


def _compute_dedup_key(row) -> tuple[str, str, str]:
    return (
        _normalize_website(row.get("website", "")),
        _normalize_phone(row.get("phone", "")),
        _normalize_name(row.get("company_name", "")),
    )


def _deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    if before == 0:
        return df

    df["_website_norm"] = df["website"].apply(_normalize_website)
    df["_phone_norm"] = df["phone"].apply(_normalize_phone)
    df["_name_norm"] = df["company_name"].apply(_normalize_name)

    df["_non_null_count"] = df[NORMALIZED_COLUMNS].apply(
        lambda r: sum(1 for v in r if v and len(str(v).strip()) > 0), axis=1
    )

    df_sorted = df.sort_values("_non_null_count", ascending=False)
    used = pd.Index([])
    result_parts = []

    has_website = df_sorted["_website_norm"].str.len() >= 3
    if has_website.any():
        web = df_sorted[has_website].drop_duplicates(subset="_website_norm", keep="first")
        result_parts.append(web)
        used = web.index

    remaining = df_sorted[~df_sorted.index.isin(used)]
    has_phone = remaining["_phone_norm"].str.len() >= 4
    if has_phone.any():
        phone = remaining[has_phone].drop_duplicates(subset="_phone_norm", keep="first")
        result_parts.append(phone)
        used = used.union(phone.index)

    remaining = df_sorted[~df_sorted.index.isin(used)]
    has_name = remaining["_name_norm"].str.len() >= 2
    if has_name.any():
        name = remaining[has_name].drop_duplicates(subset="_name_norm", keep="first")
        result_parts.append(name)
        used = used.union(name.index)

    no_match = df_sorted[~df_sorted.index.isin(used)]

    result = pd.concat(
        [p for p in result_parts + [no_match] if not p.empty],
        ignore_index=True,
    )

    result = result.drop(
        columns=["_website_norm", "_phone_norm", "_name_norm", "_non_null_count"],
        errors="ignore",
    )

    after = len(result)
    removed = before - after
    _logger.info("Dedup: %d rows \u2192 %d rows (%d duplicates removed)", before, after, removed)
    return result


def _compute_statistics(df: pd.DataFrame) -> dict[str, Any]:
    stats = {
        "total_records": len(df),
        "with_website": int((df["website"].str.len() >= 3).sum()),
        "with_phone": int((df["phone"].str.len() >= 4).sum()),
        "with_linkedin": int((df["linkedin"].str.len() >= 5).sum()),
        "with_location": int((df["location"].str.len() >= 2).sum()),
        "with_email": int((df["email"].str.len() >= 3).sum()),
        "by_platform": {},
        "unique_websites": int(
            df["website"]
            .replace("", pd.NA)
            .dropna()
            .apply(_normalize_website)
            .nunique()
        ),
        "unique_locations": int(
            df["location"]
            .replace("", pd.NA)
            .dropna()
            .nunique()
        ),
    }

    platform_counts = df["source_platform"].value_counts().to_dict()
    stats["by_platform"] = {str(k): int(v) for k, v in platform_counts.items()}

    return stats


def _print_stats(stats: dict[str, Any]) -> None:
    print("\n" + "=" * 50)
    print("   MERGE STATISTICS")
    print("=" * 50)
    print(f"   Total records:        {stats['total_records']}")
    print(f"   With website:         {stats['with_website']}")
    print(f"   With phone:           {stats['with_phone']}")
    print(f"   With LinkedIn:        {stats['with_linkedin']}")
    print(f"   With location:        {stats['with_location']}")
    print(f"   With email:           {stats['with_email']}")
    print(f"   Unique websites:      {stats['unique_websites']}")
    print(f"   Unique locations:     {stats['unique_locations']}")
    print("-" * 50)
    print("   Per platform:")
    for platform, count in stats["by_platform"].items():
        pct = count / stats["total_records"] * 100 if stats["total_records"] > 0 else 0
        print(f"      {platform:<20s} {count:>5d} ({pct:>5.1f}%)")
    print("=" * 50)


def scan_source_files() -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for source, directory in _get_source_dirs().items():
        if directory.exists():
            files = sorted(directory.glob("*.csv"))
            if source == "linkedin":
                files = [f for f in files if "linkedin_enrichment" in f.name.lower()]
            valid = [f for f in files if f.stat().st_size > 0]
            if valid:
                found[source] = valid
                _logger.info("Found %d CSV files for '%s'", len(valid), source)
            else:
                _logger.info("No valid CSV files for '%s'", source)
        else:
            _logger.info("Directory not found for '%s': %s", source, directory)
    return found


async def run_merge_engine(logger, confirm: bool = False) -> bool:
    _set_logger(logger)
    logger.info("=" * 50)
    logger.info("Master Merge Engine started")
    logger.info("=" * 50)

    source_files = scan_source_files()
    if not source_files:
        logger.warning("No source CSV files found in any export directory")
        print("\n[WARNING] No CSV files found in any export directory.")
        print("           Run scrapers first to generate data.")
        return False

    print("\n" + "=" * 55)
    print("   MASTER MERGE ENGINE")
    print("=" * 55)
    print("\nSource files found:")
    for source, files in source_files.items():
        for f in files:
            size_kb = f.stat().st_size / 1024
            print(f"   [{source.upper():<10s}] {f.name} ({size_kb:.1f} KB)")

    if not confirm:
        confirm_resp = input("\nProceed with merge? (y/n): ").strip().lower()
        if confirm_resp != "y":
            print("Cancelled.")
            return False

    all_frames: list[pd.DataFrame] = []
    total_raw = 0
    total_corrupted = 0

    for source_key, files in source_files.items():
        logger.info("Processing source: %s", source_key)
        for fpath in files:
            file_size_mb = fpath.stat().st_size / (1024 * 1024)
            df = _read_csv_safe(fpath, chunked=file_size_mb > 50)
            if df is None or df.empty:
                logger.warning("Empty or unreadable: %s", fpath.name)
                total_corrupted += 1
                continue
            total_raw += len(df)
            mapped = _map_to_normalized(df, source_key)
            if not mapped.empty:
                all_frames.append(mapped)
                logger.info("Added %d rows from %s", len(mapped), fpath.name)

    if not all_frames:
        logger.warning("No rows could be extracted from any source")
        print("\n[ERROR] No data could be extracted from the source files.")
        return False

    combined = pd.concat(all_frames, ignore_index=True)
    logger.info("Combined: %d raw rows from all sources", len(combined))

    combined = _filter_invalid_rows(combined)
    logger.info("After invalid row filter: %d rows", len(combined))

    combined = _deduplicate(combined)
    logger.info("After deduplication: %d rows", len(combined))

    for col in NORMALIZED_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""

    combined = combined[NORMALIZED_COLUMNS]

    stats = _compute_statistics(combined)
    logger.info("Statistics: %s", stats)
    _print_stats(stats)

    merged_dir = _get_export_base() / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    output_path = merged_dir / "master_leads.csv"

    try:
        tmp_path = merged_dir / f"master_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}_tmp.csv"
        combined.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        if output_path.exists():
            output_path.unlink()
        shutil.move(str(tmp_path), str(output_path))
        file_size_kb = output_path.stat().st_size / 1024
        logger.info("Master leads exported: %s (%d rows, %.1f KB)", output_path, len(combined), file_size_kb)
        print(f"\n[SUCCESS] Master leads exported to: {output_path}")
        print(f"          {len(combined)} total leads ({file_size_kb:.1f} KB)")
        return True
    except Exception as e:
        logger.error("Failed to write master CSV: %s", e)
        print(f"\n[ERROR] Failed to write master CSV: {e}")
        return False


def cleanup_old_exports(logger: logging.Logger, retention_days: int = 30, max_size_mb: int = 500) -> int:
    """Remove export files older than retention_days. Returns number of files deleted."""
    from config import BASE_DIR as cfg_base_dir

    export_root = cfg_base_dir / "exports"
    if not export_root.exists():
        logger.info("No exports directory found, skipping cleanup")
        return 0

    cutoff = datetime.now().timestamp() - retention_days * 86400
    deleted = 0
    total_size = 0

    for ext in ("csv", "json", "parquet", "xlsx"):
        for f in sorted(export_root.rglob(f"*.{ext}"), key=lambda p: p.stat().st_mtime):
            try:
                total_size += f.stat().st_size
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    logger.info("Deleted old export: %s", f)
                    deleted += 1
            except OSError as e:
                logger.warning("Failed to process %s: %s", f, e)

    size_mb = total_size / (1024 * 1024)
    if size_mb > max_size_mb:
        logger.info("Export size %.1f MB exceeds limit %d MB, triggering full cleanup", size_mb, max_size_mb)
        files_by_age = sorted([f for f in export_root.rglob("*") if f.is_file()], key=lambda p: p.stat().st_mtime)
        for f in files_by_age:
            if total_size <= max_size_mb * 1024 * 1024:
                break
            try:
                sz = f.stat().st_size
                f.unlink()
                total_size -= sz
                deleted += 1
                logger.info("Deleted oversized export: %s", f)
            except OSError:
                pass

    logger.info("Cleanup complete: %d files deleted", deleted)
    return deleted
