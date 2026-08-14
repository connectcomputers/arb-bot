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


# @app.get("/", response_class=HTMLResponse)
# async def dashboard(request: Request):
#     """Layar 1: Dashboard — ringkasan real-time."""
#     trades = _read_json(PAPER_TRADES)
#     settlements = _read_json(LEDGER)
    
#     # Hitung statistik
#     total_trades = len(trades)
#     total_pi = sum(float(t.get("pi", 0)) for t in trades)
#     matched = sum(1 for s in settlements if s.get("status") == "MATCH")
#     conflicts = sum(1 for s in settlements if s.get("status") == "SETTLEMENT_CONFLICT")
    
#     # Service status
#     try:
#         result = subprocess.run(
#             ["systemctl", "--user", "is-active", SERVICE_NAME],
#             capture_output=True, text=True, timeout=2
#         )
#         service_status = result.stdout.strip()
#     except Exception:
#         service_status = "unknown"
    
#     # return templates.TemplateResponse("index.html", {
#     #     "request": request,
#     #     "page": "dashboard",
#     #     "stats": {
#     #         "total_trades": total_trades,
#     #         "total_pi": f"${total_pi:.2f}",
#     #         "matched": matched,
#     #         "conflicts": conflicts,
#     #         "service_status": service_status,
#     #     },
#     # })

#     return templates.TemplateResponse(request, "index.html", {
#         "stats": {
#             "total_trades": total_trades,
#             "total_pi": f"${total_pi:.2f}",
#             "matched": matched,
#             "conflicts": conflicts,
#             "service_status": service_status,
#         },
#     })


def _fmt_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d/%m %H:%M")
    except Exception:
        return "-"

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
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
        return {"status": "stopped", "message": "Service stopped + alert sent"}
    except Exception as e:
        return {"status": "error", "message": str(e)}