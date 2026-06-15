"""通用工具: HTTP请求封装、文件缓存、日志"""
import json, os, time, hashlib, logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("bm-journal")

DATA_DIR = Path(__file__).parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_TTL = 3600 * 6  # 6小时缓存

def _cache_path(key: str, subdir: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    p = RAW_DIR / subdir
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{h}.json"

def cache_get(key: str, subdir: str, ttl: int = CACHE_TTL):
    """读取缓存, 未过期返回数据, 否则返回None"""
    p = _cache_path(key, subdir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text("utf-8"))
        ts = data.get("_cached_at", 0)
        if time.time() - ts < ttl:
            return data.get("payload")
    except (json.JSONDecodeError, KeyError):
        pass
    return None

def cache_set(key: str, subdir: str, payload):
    """写入缓存"""
    p = _cache_path(key, subdir)
    p.write_text(json.dumps({
        "_cached_at": time.time(),
        "_key": key,
        "payload": payload
    }, ensure_ascii=False, indent=2), "utf-8")

def fetch_json(url: str, params: dict = None, headers: dict = None,
               timeout: int = 30, retries: int = 2) -> dict | list | None:
    """通用JSON请求, 带重试"""
    import requests
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers,
                                timeout=timeout)
            if resp.status_code == 429:
                wait = min(60, 5 * (attempt + 1))
                log.warning(f"429 rate limited, waiting {wait}s: {url}")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            log.warning(f"Timeout (attempt {attempt+1}): {url}")
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
        except requests.exceptions.RequestException as e:
            log.error(f"Request failed: {e}")
            if attempt < retries:
                time.sleep(2)
    return None

def save_raw(subdir: str, filename: str, data, pretty: bool = True):
    """保存原始数据到 data/raw/{subdir}/{filename}.json"""
    p = RAW_DIR / subdir
    p.mkdir(parents=True, exist_ok=True)
    fp = p / f"{filename}.json"
    indent = 2 if pretty else None
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=indent, default=str), "utf-8")
    log.info(f"Saved raw data: {fp.relative_to(DATA_DIR)}")
    return fp

def load_raw(subdir: str, filename: str):
    """读取原始数据"""
    fp = RAW_DIR / subdir / f"{filename}.json"
    if not fp.exists():
        return None
    return json.loads(fp.read_text("utf-8"))

def safe_float(val, default=None):
    """安全浮点转换"""
    if val is None:
        return default
    try:
        v = float(val)
        return v if v == v else default  # NaN check
    except (ValueError, TypeError):
        return default

def pct_change(current, previous):
    """计算百分比变化, 保留1位小数"""
    if previous is None or previous == 0 or current is None:
        return None
    return round((current - previous) / abs(previous) * 100, 1)

def fmt_number(val, unit=""):
    """格式化数字显示"""
    if val is None:
        return "N/A"
    if abs(val) >= 1e12:
        return f"{val/1e12:.1f}万亿{unit}"
    if abs(val) >= 1e8:
        return f"{val/1e8:.1f}亿{unit}"
    if abs(val) >= 1e4:
        return f"{val/1e4:.1f}万{unit}"
    return f"{val:,.1f}{unit}"
