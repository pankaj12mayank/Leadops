import csv
import json
import logging
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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


def _load_export_base() -> Path:
    try:
        cfg_path = BASE_DIR / "config.json"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            exports_rel = cfg.get("paths", {}).get("exports", "exports")
            return (BASE_DIR / exports_rel).resolve()
    except Exception:
        pass
    return BASE_DIR / "exports"


_EXPORT_BASE = _load_export_base()


SOURCE_DIRS = {
    "clutch": _EXPORT_BASE / "clutch",
    "goodfirms": _EXPORT_BASE / "goodfirms",
    "maps": _EXPORT_BASE / "maps",
    "linkedin": _EXPORT_BASE / "linkedin",
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

_logger: Optional[logging.Logger] = None


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


def _read_csv_safe(path: Path) -> Optional[pd.DataFrame]:
    for attempt in range(3):
        try:
            if attempt == 0:
                df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
            elif attempt == 1:
                df = pd.read_csv(
                    path,
                    encoding="utf-8-sig",
                    on_bad_lines="skip",
                    low_memory=False,
                )
            else:
                raw_rows = []
                with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
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


def _map_to_normalized(df: pd.DataFrame, source_key: str) -> pd.DataFrame:
    mapping = COLUMN_MAP[source_key]
    rows = []
    used_map = {}

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


def _compute_dedup_key(row) -> Tuple[str, str, str]:
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


def _compute_statistics(df: pd.DataFrame) -> Dict[str, Any]:
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


def _print_stats(stats: Dict[str, Any]) -> None:
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


def scan_source_files() -> Dict[str, List[Path]]:
    found: Dict[str, List[Path]] = {}
    for source, directory in SOURCE_DIRS.items():
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


async def run_merge_engine(logger) -> bool:
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

    confirm = input("\nProceed with merge? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return False

    all_frames: List[pd.DataFrame] = []
    total_raw = 0
    total_corrupted = 0

    for source_key, files in source_files.items():
        logger.info("Processing source: %s", source_key)
        for fpath in files:
            df = _read_csv_safe(fpath)
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

    merged_dir = _EXPORT_BASE / "merged"
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
