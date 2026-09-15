"""Alert dispatcher: Telegram + Banner + File log."""
import json
import time
from pathlib import Path
from typing import List, Optional

ALERTS_FILE = Path("data/alerts.json")
ALERT_LOG = Path("data/alerts.log")
RATE_LIMIT_SEC = 600  # 10 menit per kondisi

_alert_cache = {}  # condition_key -> last_sent_ts

def _load_alerts() -> dict:
    """Load alerts dari file."""
    if ALERTS_FILE.exists():
        try:
            return json.loads(ALERTS_FILE.read_text())
        except Exception:
            pass
    return {"active": [], "history": []}

def _save_alerts(data: dict):
    """Save alerts ke file."""
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_FILE.write_text(json.dumps(data, indent=2))

def _rate_limit_ok(condition_key: str) -> bool:
    """Cek apakah kondisi ini boleh dikirim lagi (rate limit 10 menit)."""
    last = _alert_cache.get(condition_key, 0)
    return (time.time() - last) >= RATE_LIMIT_SEC

def dispatch_alert(level: str, message: str, condition_key: str = None):
    """Kirim alert ke semua channel yang aktif.
    
    Args:
        level: 'critical', 'warning', 'info'
        message: pesan alert
        condition_key: key unik untuk rate limiting (default: message[:50])
    """
    if condition_key is None:
        condition_key = message[:50]
    
    # Rate limiting
    if not _rate_limit_ok(condition_key):
        return
    
    _alert_cache[condition_key] = time.time()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    
    # 1. File log (selalu aktif)
    try:
        ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERT_LOG, "a") as f:
            f.write(f"{ts} [{level.upper()}] {message}\n")
    except Exception:
        pass
    
    # 2. Banner dashboard (simpan di alerts.json)
    try:
        alerts = _load_alerts()
        alert_obj = {"ts": ts, "level": level, "message": message}
        alerts["active"].append(alert_obj)
        alerts["active"] = alerts["active"][-20:]  # max 20 active
        alerts["history"].append(alert_obj)
        alerts["history"] = alerts["history"][-100:]  # max 100 history
        _save_alerts(alerts)
    except Exception:
        pass
    
    # 3. Telegram (bila dikonfigurasi)
    try:
        from app.config_store import load_config
        cfg = load_config()
        telegram_cfg = cfg.get("alert_telegram", {})
        bot_token = telegram_cfg.get("bot_token", "").strip()
        chat_id = telegram_cfg.get("chat_id", "").strip()
        
        if bot_token and chat_id:
            import httpx
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": f"[{level.upper()}] {message}",
                "parse_mode": "Markdown"
            }
            httpx.post(url, json=payload, timeout=10)
    except Exception:
        pass

def clear_alert(condition_key: str):
    """Hapus alert dari daftar active."""
    try:
        alerts = _load_alerts()
        alerts["active"] = [a for a in alerts["active"] if condition_key not in a.get("message", "")]
        _save_alerts(alerts)
    except Exception:
        pass

def get_active_alerts() -> List[dict]:
    """Kembalikan daftar alert aktif (untuk banner dashboard)."""
    try:
        alerts = _load_alerts()
        return alerts.get("active", [])
    except Exception:
        return []
