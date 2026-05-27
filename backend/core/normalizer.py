from typing import Any, Optional

NORMALIZED_FIELDS = [
    "source",
    "business_name",
    "website",
    "phone",
    "email",
    "location",
    "category",
    "rating",
]

def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _normalize_clutch(raw: dict) -> dict:
    return {
        "source": "clutch",
        "business_name": raw.get("company_name", ""),
        "website": raw.get("website", ""),
        "phone": "",
        "email": "",
        "location": raw.get("location", ""),
        "category": "",
        "rating": _safe_float(raw.get("rating")),
    }


def _normalize_goodfirms(raw: dict) -> dict:
    return {
        "source": "goodfirms",
        "business_name": raw.get("company_name", ""),
        "website": raw.get("website", ""),
        "phone": "",
        "email": "",
        "location": raw.get("location", ""),
        "category": "",
        "rating": _safe_float(raw.get("rating")),
    }


def _normalize_maps(raw: dict) -> dict:
    return {
        "source": "google_maps",
        "business_name": raw.get("business_name", ""),
        "website": raw.get("website", ""),
        "phone": raw.get("phone", ""),
        "email": "",
        "location": raw.get("address", ""),
        "category": raw.get("category", ""),
        "rating": _safe_float(raw.get("rating")),
    }


def _normalize_linkedin(raw: dict) -> dict:
    name = raw.get("matched_company_name", "") or raw.get("input_company_name", "")
    return {
        "source": "linkedin",
        "business_name": name,
        "website": raw.get("input_website", ""),
        "phone": "",
        "email": "",
        "location": "",
        "category": "",
        "rating": None,
    }


_NORMALIZERS = {
    "clutch": _normalize_clutch,
    "goodfirms": _normalize_goodfirms,
    "maps": _normalize_maps,
    "linkedin": _normalize_linkedin,
}


def normalize_lead(source: str, raw: dict) -> dict:
    normalizer = _NORMALIZERS.get(source)
    if normalizer is None:
        raise ValueError(f"Unknown source: {source}")
    return normalizer(raw)


def normalize_leads(source: str, raw_leads: list[dict]) -> list[dict]:
    return [normalize_lead(source, lead) for lead in raw_leads]
