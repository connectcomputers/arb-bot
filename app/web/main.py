"""
UI Dashboard — Tahap 11.
FastAPI app dengan 7 layar audit untuk klien + kill switch.
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config_store import load_creds, save_creds, load_config, set_venue_valid
from app.venue_auth import check_venue

from fastapi.responses import RedirectResponse
# from app.venue_markets import top_markets
from app.venue_markets import venue_categories
from app.config_store import (load_creds, save_creds, load_config,
                              save_config, set_venue_valid)
from app import engine
from app.venue_positions import get_positions

LIMIT_KEYS = ["modal_total", "modal_per_op", "sl",
              "tp", "min_profit", "rugi_harian"]


def config_complete(cfg: dict) -> bool:
    venues_ok = sum(1 for s in cfg["venues"].values() if s.get("valid"))
    pairs = cfg.get("pairs") or {}
    n_pairs = sum(len(v) for v in pairs.values())
    limits = cfg.get("limits") or {}
    return (venues_ok >= 2 and n_pairs >= 1
            and all(str(limits.get(k, "")).strip() != "" for k in LIMIT_KEYS))

# VENUE_FIELDS = {
#     "polymarket": [("private_key", "Private Key Wallet (0x…)")],
#     "kalshi": [("api_key_id", "API Key ID"),
#                ("private_key_pem", "RSA Private Key (-----BEGIN …)")],
#     "limitless": [("api_key", "API Key"), ("api_secret", "API Secret")],
# }

# VENUE_FIELDS = {
#     "polymarket": [("private_key", "Private Key Wallet (0x…)")],
#     "kalshi": [("api_key_id", "API Key ID"),
#                ("private_key_pem", "RSA Private Key (isi PEM atau path file)"),
#                ("base_url", "Base URL (OPSIONAL — kosong = produksi; isi https://demo-api.kalshi.co untuk demo)")],
#     "limitless": [("api_key", "API Key"), ("api_secret", "API Secret")],
# }

VENUES_SCHEMA = {
    "polymarket": [
        ("private_key", "Private Key Wallet (0x…)"),
        ("proxy_address", "Deposit/Proxy Wallet Address (opsional, untuk order)"),
    ],
    "kalshi": [
        ("api_key_id", "API Key ID"),
        ("private_key_pem", "RSA Private Key (PEM)"),
        ("base_url", "Base URL (kosong = produksi)"),
    ],
    "limitless": [
        ("api_key", "API Key"),
        ("api_secret", "API Secret"),
        ("partner_wallet", "Partner Wallet Address (opsional, untuk order)"),
    ],
}

app = FastAPI(title="Arb Bot Dashboard", version="1.0")
templates = Jinja2Templates(directory="app/web/templates")

# Paths
DATA_DIR = Path("data")
LOOP_LOG = DATA_DIR / "loop.log"
PAPER_TRADES = DATA_DIR / "paper_trades.json"
LEDGER = DATA_DIR / "ledger.json"
SERVICE_NAME = "arb-bot-loop.service"


def _read_json(path: Path) -> list:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return []
    return []


def _tail_log(path: Path, lines: int = 50) -> list:
    if not path.exists():
        return []
    with open(path) as f:
        all_lines = f.readlines()
        return [json.loads(line) for line in all_lines[-lines:]]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not config_complete(load_config()):
        return RedirectResponse("/setup")
    st = engine.status()
    if st.get("kill") or st.get("need_rearm"):
        return RedirectResponse("/setup", status_code=303)   # sesi berakhir → setup
    return templates.TemplateResponse(request, "index.html", {})

@app.post("/api/exec/micro")
async def exec_micro(request: Request):
    data = await request.json()
    return engine.micro_exec(data.get("venue"), dry=bool(data.get("dry")))

@app.post("/api/engine/refresh")
async def engine_refresh():
    return engine.refresh()          # engine.refresh() sendiri menolak saat kill/berhenti

@app.post("/api/pairs")
async def api_pairs(request: Request):
    cfg = load_config()
    cfg["pairs"] = (await request.json()).get("pairs", {})
    save_config(cfg)
    engine.unkill()                  # ✅ Simpan di setup = buka sesi baru
    return {"saved": True}

@app.get("/limits", response_class=HTMLResponse)
async def limits(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(request, "limits.html", {
        "limits": cfg.get("limits", {}),
        "venues_valid": [v for v, s in cfg["venues"].items() if s.get("valid")],
        "pairs": cfg.get("pairs", {}),
    })

@app.post("/api/limits")
async def api_limits(request: Request):
    cfg = load_config()
    cfg["limits"] = (await request.json()).get("limits", {})
    save_config(cfg)
    engine.unkill()                  # ✅
    return {"saved": True}

@app.get("/api/markets")
async def api_markets(venue: str):
    creds = load_creds().get(venue, {})
    return {"venue": venue, "categories": venue_categories(venue, creds)}

@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    cfg = load_config()
    saved = {v: bool(load_creds().get(v)) for v in VENUES_SCHEMA}
    return templates.TemplateResponse(request, "setup.html",
        {"venues": VENUES_SCHEMA, "cfg": cfg, "saved": saved})

@app.post("/api/credentials")
async def api_credentials(request: Request):
    data = await request.json()
    save_creds(data.get("venue"), data.get("creds", {}))
    engine.unkill()                  # ✅
    return {"saved": True}

@app.post("/api/cek-api")
async def api_cek(request: Request):
    venue = (await request.json()).get("venue")
    ok, msg = check_venue(venue, load_creds().get(venue, {}))
    set_venue_valid(venue, ok)
    return {"ok": ok, "message": msg}   # cek saja TIDAK membuka kunci

def _fmt_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d/%m %H:%M")
    except Exception:
        return "-"

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not config_complete(load_config()):
        return RedirectResponse("/setup")
    return templates.TemplateResponse(request, "index.html", {})

    """Layar 1: Dashboard — ringkasan real-time + aktivitas scanner."""
    trades = _read_json(PAPER_TRADES)
    settlements = _read_json(LEDGER)

    total_trades = len(trades)
    total_pi = sum(float(t.get("pi", 0)) for t in trades)
    matched = sum(1 for s in settlements if s.get("status") == "MATCH")
    conflicts = sum(1 for s in settlements if s.get("status") == "SETTLEMENT_CONFLICT")

    logs = _tail_log(LOOP_LOG, 1)
    last = logs[0] if logs else None
    scanner = {
        "cycle": last.get("cycle", "-") if last else "-",
        "last_scan": (last.get("timestamp", "-") or "-").replace("T", " ")[:19] if last else "-",
        "markets": (last.get("poly", 0) + last.get("kalshi", 0)) if last else 0,
        "locked": last.get("locked", 0) if last else 0,
        "errors": len(last.get("errors", [])) if last else 0,
    }

    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True, text=True, timeout=2
        )
        service_status = result.stdout.strip()
    except Exception:
        service_status = "unknown"

    recent_trades = [{
        "time": _fmt_ts(t.get("ts")),
        "key": str(t.get("key"))[:40],
        "venues": " × ".join(sorted({o.get("venue", "?") for o in t.get("orders", [])})),
        "pi": t.get("pi", "0"),
    } for t in reversed(trades)][:10]

    recent_settlements = [{
        "time": _fmt_ts(s.get("ts")),
        "key": str(s.get("key"))[:40],
        "status": s.get("status"),
        "realized": s.get("realized_pnl") or "-",
        "expected": s.get("expected_pi"),
    } for s in reversed(settlements)][:10]

    return templates.TemplateResponse(request, "index.html", {
        "stats": {
            "total_trades": total_trades,
            "total_pi": f"${total_pi:.2f}",
            "matched": matched,
            "conflicts": conflicts,
            "service_status": service_status,
        },
        "scanner": scanner,
        "recent_trades": recent_trades,
        "recent_settlements": recent_settlements,
    })

@app.get("/api/venue-feed")
async def venue_feed():
    cfg = load_config()
    creds = load_creds()
    return {"venues": [{
        "venue": v,
        "valid": bool(s.get("valid")),
        "cats": (cfg.get("pairs") or {}).get(v, []),
        "positions": get_positions(v, creds.get(v, {})) if s.get("valid") else [],
    } for v, s in cfg["venues"].items()]}

@app.post("/api/engine/start")
async def engine_start(request: Request):
    mode = (await request.json()).get("mode", "paper")
    return engine.start(mode)        # start menolak sendiri bila kill aktif

@app.post("/api/engine/stop")
async def engine_stop():
    engine.stop()                    # stop real → need_rearm (logika di engine)
    return {"ok": True}

@app.post("/api/engine/kill")
async def engine_kill():
    engine.kill()                    # kill → kunci + need_rearm
    return {"ok": True}

@app.get("/api/engine/status")
async def engine_status():
    return engine.status()

@app.get("/api/pairing")
async def api_pairing():
    """Layar 2: Pairing — daftar market locked."""
    logs = _tail_log(LOOP_LOG, 100)
    locked_pairs = []
    for log in logs:
        if log.get("locked", 0) > 0:
            locked_pairs.append({
                "timestamp": log.get("timestamp"),
                "count": log.get("locked"),
            })
    return {"pairs": locked_pairs}


@app.get("/api/opportunities")
async def api_opportunities():
    """Layar 3: Peluang — signal decisions."""
    logs = _tail_log(LOOP_LOG, 100)
    opportunities = []
    for log in logs:
        if log.get("decisions"):
            for dec in log["decisions"]:
                opportunities.append({
                    "timestamp": log.get("timestamp"),
                    "key": dec.get("key"),
                    "direction": dec.get("direction"),
                    "pi": dec.get("pi"),
                    "execute": dec.get("execute"),
                })
    return {"opportunities": opportunities}


@app.get("/api/positions")
async def api_positions():
    """Layar 4: Posisi — paper trades aktif."""
    trades = _read_json(PAPER_TRADES)
    return {"positions": trades[-20:]}  # 20 terakhir


@app.get("/api/settlement")
async def api_settlement():
    """Layar 5: Settlement — hasil rekonsiliasi."""
    settlements = _read_json(LEDGER)
    return {"settlements": settlements[-50:]}  # 50 terakhir


@app.get("/api/log")
async def api_log():
    """Layar 6: Log — tail log scanner."""
    logs = _tail_log(LOOP_LOG, 100)
    return {"logs": logs}


@app.get("/api/config")
async def api_config():
    """Layar 7: Config — parameter sistem."""
    return {
        "config": {
            "min_profit_pct": "0.008",
            "buffer_slippage": "0.005",
            "loop_interval": "60",
            "limit_per_venue": "100",
        }
    }


@app.post("/api/kill-switch")
async def kill_switch():
    """KILL SWITCH: Stop service + alert Telegram."""
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", SERVICE_NAME],
            timeout=5
        )
        # Kirim alert
        from app.alerts.telegram import send_text
        import asyncio
        asyncio.create_task(send_text(
            "🛑 <b>KILL SWITCH ACTIVATED</b>\n"
            "Service dihentikan manual via dashboard."
        ))
    except Exception as e:
        return {"status": "error", "message": str(e)}