import builtins
import json
import logging
from datetime import datetime

try:
    import numpy as np
except ImportError:
    np = None

logger = logging.getLogger(__name__)

TYPE_TAG = "__pytype__:"
DT_TAG = "__dt__:"
UNKNOWN_TAG = "__unknown__:"


def serialize_json(value) -> str:
    """
    Serializes a Python structure to a JSON string.
    Handles types, datetimes, NumPy data, and flags unknown objects with a prefix.
    """

    def json_type_fallback(obj):
        # 1. Handle NumPy arrays
        if np and isinstance(obj, np.ndarray):
            return obj.tolist()

        # 2. Handle NumPy scalar data types (e.g., np.int64, np.float64)
        if np and isinstance(obj, np.generic):
            return obj.item()

        # 3. Handle Python 'type' objects (e.g., float, int)
        if isinstance(obj, type):
            return f"{TYPE_TAG}{obj.__name__}"

        # 4. Handle datetime objects
        if isinstance(obj, datetime):
            return f"{DT_TAG}{obj.isoformat()}"

        # 5. Handle other unknown types explicitly with a prefix tag
        return f"{UNKNOWN_TAG}{str(obj)}"

    try:
        return json.dumps(value, default=json_type_fallback, ensure_ascii=False)
    except Exception:
        logger.warning(f"Could not serialize object to JSON: {value}", exc_info=True)
        return "{}"


def _resolve_tagged_string(val):
    """Detects and recovers tagged strings (Types, Datetimes, Unknowns) instantly."""
    if isinstance(val, str):
        if val.startswith(TYPE_TAG):
            type_name = val.split(TYPE_TAG, 1)[1]
            if hasattr(builtins, type_name):
                target_type = getattr(builtins, type_name)
                if isinstance(target_type, type):
                    return target_type

        elif val.startswith(DT_TAG):
            try:
                iso_str = val.split(DT_TAG, 1)[1]
                return datetime.fromisoformat(iso_str)
            except (ValueError, TypeError):
                return val

        elif val.startswith(UNKNOWN_TAG):
            return val.split(UNKNOWN_TAG, 1)[1]

    elif isinstance(val, list):
        return [_resolve_tagged_string(item) for item in val]

    return val


def _fast_parser_hook(pairs):
    """
    High-performance parser hook that intercepts elements during the
    C-level JSON decoding pass. Handles multidimensional arrays cleanly.
    """
    resolved_dict = {}
    for key, value in pairs:
        # Ruft jetzt die erweiterte Prüfung auf, die auch Unterlisten scannt
        resolved_dict[key] = _resolve_tagged_string(value)
    return resolved_dict



def deserialize_json(json_str: str) -> dict:
    """
    Deserializes a JSON string back into a Python structure.
    Recovers types, datetimes, and flags unknown markers with zero post-processing overhead.
    """
    if not json_str:
        return {}

    try:
        decoder = json.JSONDecoder(object_hook=None,
                                   object_pairs_hook=_fast_parser_hook)
        return decoder.decode(json_str)
    except Exception:
        logger.error("❌ Failed to deserialize JSON string and restore pipeline types",
                     exc_info=True)
        return {}

