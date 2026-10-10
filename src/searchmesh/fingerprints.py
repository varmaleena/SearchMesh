import hashlib
import json
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fingerprint(scope, params):
    # Preserve query punctuation, whitespace, filters and list ordering.
    return digest({"scope": scope, "params": params})


def content_hash(raw):
    return digest({k: v for k, v in raw.items() if k not in {"search_metadata", "search_parameters"}})


def provider_time(raw):
    value = raw.get("search_metadata", {}).get("created_at")
    if not isinstance(value, str):
        return None
    try:
        value = value.replace(" UTC", "+00:00").replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        return dt.timestamp() if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()

