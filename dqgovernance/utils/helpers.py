import uuid
import hashlib
import json
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
from dateutil import parser as date_parser

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def json_serializer(obj: Any) -> Any:
    if HAS_NUMPY:
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def safe_json_dumps(obj: Any, **kwargs) -> str:
    return json.dumps(obj, ensure_ascii=False, default=json_serializer, **kwargs)


def generate_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16].upper()}"


def parse_date(date_str: Any) -> Optional[date]:
    if date_str is None:
        return None
    if isinstance(date_str, date):
        return date_str
    if isinstance(date_str, datetime):
        return date_str.date()
    try:
        return date_parser.parse(str(date_str)).date()
    except (ValueError, TypeError):
        return None


def format_date(d: Any, fmt: str = "%Y-%m-%d") -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        return d
    return d.strftime(fmt)


def get_severity_weight(severity: str) -> int:
    weights = {"critical": 100, "high": 70, "medium": 40, "low": 10}
    return weights.get(severity.lower(), 10)


def calculate_priority(
    severity: str, affected_records: int, business_impact: float = 0.0) -> str:
    base_score = get_severity_weight(severity)
    volume_score = min(affected_records / 1000, 1.0) * 30
    total_score = base_score + volume_score + (business_impact * 100)

    if total_score >= 150:
        return "P0"
    elif total_score >= 120:
        return "P1"
    elif total_score >= 90:
        return "P2"
    elif total_score >= 60:
        return "P3"
    else:
        return "P4"


def calculate_sla_hours(severity: str) -> int:
    slas = {"critical": 24, "high": 72, "medium": 168, "low": 336}
    return slas.get(severity.lower(), 168)


def hash_value(value: str, algorithm: str = "sha256") -> str:
    if not value:
        return ""
    h = hashlib.new(algorithm)
    h.update(str(value).encode("utf-8"))
    return h.hexdigest()


def mask_string(s: str, visible_start: int = 0, visible_end: int = 0, mask_char: str = "*") -> str:
    if not s:
        return ""
    s = str(s)
    length = len(s)
    if length <= visible_start + visible_end:
        return s
    masked_length = length - visible_start - visible_end
    return s[:visible_start] + (mask_char * masked_length) + s[-visible_end:] if visible_end > 0 else s[:visible_start] + (mask_char * masked_length)


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def get_date_range(start_date: date, end_date: date) -> List[date]:
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def is_valid_id_card(id_card: str) -> bool:
    if not id_card:
        return False
    id_card = str(id_card).strip().upper()
    if len(id_card) == 15:
        try:
            int(id_card)
            return True
        except ValueError:
            return False
    if len(id_card) == 18:
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        check_codes = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]
        try:
            total = sum(int(id_card[i]) * weights[i] for i in range(17))
            return id_card[17] == check_codes[total % 11]
        except (ValueError, IndexError):
            return False
    return False


def is_valid_phone(phone: str) -> bool:
    if not phone or len(phone) != 11:
        return False
    return phone.startswith("1") and phone[1] in "3456789" and phone.isdigit()


def is_valid_email(email: str) -> bool:
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email or ""))


def safe_eval(expression: str, context: Dict[str, Any]) -> Any:
    try:
        return eval(expression, {"__builtins__": {}}, context)
    except Exception:
        return False
