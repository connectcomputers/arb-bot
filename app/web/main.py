# /app/web/main.py
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

# VENUES_SCHEMA = {
#     "polymarket": [
#         ("private_key", "Private Key Wallet (0x…)"),
#         ("proxy_address", "Deposit/Proxy Wallet Address (opsional, untuk order)"),
#     ],
#     "kalshi": [
#         ("api_key_id", "API Key ID"),
#         ("private_key_pem", "RSA Private Key (PEM)"),
#         ("base_url", "Base URL (kosong = produksi)"),
#     ],
#     "limitless": [
#         ("api_key", "API Key", "text"),
#         ("api_secret", "API Secret (base64)", "text"),

#         ("wallet_mode", "Mode Wallet", "select",
#         ["smartWallet", "eoa"]),

#         ("smart_wallet_profile_id",
#         "Limitless Wallet — Profile ID (untuk Managed Wallet)",
#         "text"),

#         ("smart_wallet_address",
#         "Limitless Wallet — Address (opsional, untuk verifikasi)",
#         "text"),

#         ("eoa_profile_id",
#         "Wallet Pribadi — Limitless Profile ID",
#         "text"),

#         ("wallet_pk",
#         "Wallet Pribadi — Private Key (0x + 64 hex)",
#         "text"),

#         ("_note_sw",
#         "Wallet Limitless / Managed = server Limitless yang melakukan signing. "
#         "Tidak membutuhkan private key.",
#         "info"),

#         ("_note_eoa",
#         "Wallet Pribadi / EOA = bot melakukan EIP-712 signing. "
#         "Private key wajib 64 hex.",
#         "info"),
#     ]
# }

# dari chatgpt
VENUES_SCHEMA = {
    "polymarket": [
        ("private_key", "Private Key Wallet (0x…)", "text"),
        ("proxy_address", "Deposit/Proxy Wallet Address (opsional, untuk order)", "text"),
        ("proxy_url", "Proxy URL eksekusi (opsional: http://user:pass@host:port wilayah didukung)", "text"),
    ],

    "kalshi": [
        ("api_key_id", "API Key ID", "text"),
        ("private_key_pem", "RSA Private Key (PEM)", "text"),
        ("base_url", "Base URL (kosong = produksi)", "text"),
    ],

    "limitless": [
        ("api_key", "API Key", "text"),

        ("api_secret", "API Secret (base64)", "text"),

        (
            "wallet_mode",
            "Pilih Wallet untuk Order Limitless",
            "select",
            [
                ("smartWallet", "Wallet Limitless"),
                ("eoa", "Wallet Pribadi (EOA)"),
            ],
        ),

        (
            "smart_wallet_profile_id",
            "Limitless Wallet Profile ID",
            "text",
        ),

        (
            "wallet_pk",
            "Private Key Wallet Pribadi (0x + 64 hex)",
            "text",
        ),

        (
            "_note_sw",
            "Wallet Limitless: order menggunakan delegated signing "
            "melalui server-wallet child profile. Tidak membutuhkan private key.",
            "info",
        ),

        (
            "_note_eoa",
            "Wallet Pribadi: order ditandatangani EOA menggunakan "
            "private key 0x + 64 hex. Jangan masukkan alamat 0x + 40 hex.",
            "info",
        ),
    ],
}

app = FastAPI(title="Arb Bot Dashboard", version="1.0")

@app.middleware("http")
async def _gate_setup(request, call_next):
    """Belum ada venue tervalidasi → paksa ke /setup."""
    if request.url.path == "/":
        from app.config_store import load_creds as _lc, load_config as _lcfg
        from fastapi.responses import RedirectResponse as _RR
        _vs = ("polymarket", "kalshi", "limitless")
        _cfg = (_lcfg() or {}).get("venue_valid", {}) or {}
        _cr = _lc() or {}
        _ok = any(_cfg.get(v) for v in _vs) or \
              any((_cr.get(v) or {}).get("api_valid") for v in _vs)
        if not _ok:
            return _RR("/setup", status_code=302)
    return await call_next(request)

@app.on_event("startup")
def _reset_stale_engine_state():
    """Proses baru = engine pasti belum jalan; jangan warisi running:true."""
    import json as _j
    from pathlib import Path as _P
    p = _P("data/live_state.json")
    try:
        d = _j.loads(p.read_text())
        if d.get("running"):
            d["running"] = False
            p.write_text(_j.dumps(d, indent=2))
    except Exception:
        pass
    
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

@app.post("/api/engine/reset-spend")
def engine_reset_spend():
    """Reset counter belanja harian (cap) — untuk tes/demo."""
    import time as _t
    st = engine._read()
    st["spend"] = {"today": _t.strftime("%Y-%m-%d"), "amount": 0.0}
    st.pop("auto_stop", None)
    engine._write(st)
    return {"ok": True, "message": "cap harian direset (spend=$0.00)"}

@app.get("/api/saldo")
def api_saldo():
    """Endpoint saldo real-time semua venue."""
    from app.saldo_service import get_all_saldo
    return get_all_saldo()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
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
def engine_refresh():
    return engine.refresh()          # engine.refresh() sendiri menolak saat kill/berhenti

@app.post("/api/pairs")
async def api_pairs(request: Request):
    cfg = load_config()
    cfg["pairs"] = (await request.json()).get("pairs", {})
    save_config(cfg)
    engine.unkill()                  # ✅ Simpan di setup = buka sesi baru
    return {"saved": True}

@app.get("/limits", response_class=HTMLResponse)
def limits(request: Request):
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
def api_markets(venue: str):
    creds = load_creds().get(venue, {})
    return {"venue": venue, "categories": venue_categories(venue, creds)}

# @app.get("/setup", response_class=HTMLResponse)
# async def setup(request: Request):
#     cfg = load_config()
#     saved = {v: bool(load_creds().get(v)) for v in VENUES_SCHEMA}
#     return templates.TemplateResponse(request, "setup.html",
#         {"venues": VENUES_SCHEMA, "cfg": cfg, "saved": saved})

@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    cfg = load_config()
    creds = load_creds()

    saved = {
        v: bool(creds.get(v))
        for v in VENUES_SCHEMA
    }

    limitless = creds.get("limitless", {})

    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "venues": VENUES_SCHEMA,
            "cfg": cfg,
            "saved": saved,
            "limitless_mode": limitless.get(
                "wallet_mode",
                "smartWallet",
            ),
        },
    )

# @app.post("/api/credentials")
# async def api_credentials(request: Request):
#     data = await request.json()
#     save_creds(data.get("venue"), data.get("creds", {}))
#     engine.unkill()                  # ✅
#     return {"saved": True}

# dari chatgpt
@app.post("/api/credentials")
async def api_credentials(request: Request):
    data = await request.json()

    venue = data.get("venue")
    incoming = data.get("creds") or {}

    if not venue:
        return {
            "saved": False,
            "message": "venue kosong",
        }

    current = load_creds().get(venue, {})

    # Merge:
    # field kosong dari browser tidak menghapus credential
    # yang sudah tersimpan.
    merged = dict(current)

    for key, value in incoming.items():
        if value is None:
            continue

        value = str(value).strip()

        # Field internal/info tidak disimpan
        if key.startswith("_"):
            continue

        # Jangan overwrite credential lama dengan string kosong
        if value == "":
            continue

        merged[key] = value

    save_creds(venue, merged)

    engine.unkill()

    return {
        "saved": True,
        "venue": venue,
    }

@app.post("/api/cek-api")
async def api_cek(request: Request):
    venue = (await request.json()).get("venue")
    # ok, msg = check_venue(venue, load_creds().get(venue, {}))

    # _allc = load_creds() or {}
    # _cr = dict(_allc.get(venue, {}) or {})
    # ok, msg = check_venue(venue, _cr)
    # if ok:
    #     _cr["api_valid"] = True
    # else:
    #     _cr.pop("api_valid", None)
    # _allc[venue] = _cr
    # save_creds(_allc)   # sesuaikan nama bila hasil grep berbeda (mis. update_creds)

    _cr = dict((load_creds() or {}).get(venue, {}) or {})
    ok, msg = check_venue(venue, _cr)
    try:
        set_venue_valid(venue, bool(ok))
    except Exception as _e:
        print("warn set_venue_valid:", _e)

    set_venue_valid(venue, ok)
    return {"ok": ok, "message": msg}   # cek saja TIDAK membuka kunci

def _fmt_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%d/%m %H:%M")
    except Exception:
        return "-"

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
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
def venue_feed():
    cfg = load_config()          # ← TAMBAHKAN BARIS INI
    creds = load_creds()
    return {"venues": [{
        "venue": v,
        "valid": bool(s.get("valid")),
        "cats": (cfg.get("pairs") or {}).get(v, []),
        "positions": get_positions(v, creds.get(v, {})) if s.get("valid") else [],
    } for v, s in cfg["venues"].items()]}

@app.post("/api/engine/start")
async def engine_start(request: Request):
    """Start engine; bila sudah jalan dengan mode berbeda, switch otomatis."""
    import time as _t
    from app import engine as _eng
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = body.get("mode", "paper")
    st = _eng.status()
    if st.get("running") and st.get("mode") != mode:
        _eng.stop()
        _t.sleep(0.6)
    ok, msg = _eng.start(mode)
    return {"ok": ok, "message": msg}

@app.post("/api/engine/stop")
def engine_stop():
    engine.stop()                    # stop real → need_rearm (logika di engine)
    return {"ok": True}

@app.post("/api/engine/kill")
def engine_kill():
    engine.kill()                    # kill → kunci + need_rearm
    return {"ok": True}

@app.get("/api/engine/status")
def engine_status():
    return engine.status()

@app.get("/api/pairing")
def api_pairing():
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
def api_opportunities():
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
def api_positions():
    """Layar 4: Posisi — paper trades aktif."""
    trades = _read_json(PAPER_TRADES)
    return {"positions": trades[-20:]}  # 20 terakhir


@app.get("/api/settlement")
def api_settlement():
    """Layar 5: Settlement — hasil rekonsiliasi."""
    settlements = _read_json(LEDGER)
    return {"settlements": settlements[-50:]}  # 50 terakhir


@app.get("/api/log")
def api_log():
    """Layar 6: Log — tail log scanner."""
    logs = _tail_log(LOOP_LOG, 100)
    return {"logs": logs}


@app.get("/api/config")
def api_config():
    """Layar 7: Config — parameter sistem."""
    return {
        "config": {
            "min_profit_pct": "0.008",
            "buffer_slippage": "0.005",
            "loop_interval": "60",
            "limit_per_venue": "100",
        }
    }




    return load_config()

@app.get("/api/alerts")
def api_alerts():
    """Kembalikan daftar alert aktif untuk banner dashboard."""
    try:
        from app.alert import get_active_alerts
        alerts = get_active_alerts()
        return {"alerts": alerts if isinstance(alerts, list) else []}
    except Exception as e:
        # Return kosong bila error, jangan 500
        return {"alerts": [], "error": str(e)[:100]}@app.post("/api/kill-switch")
def kill_switch():
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


@app.get("/api/reconciliation")
def api_reconciliation():
    """Data rekonsiliasi: saldo baseline vs sekarang + trades."""
    from app.baseline import load_baseline
    import json
    from pathlib import Path as _P2
    
    baseline = load_baseline()
    
    try:
        state = json.loads(_P2("data/live_state.json").read_text())
        trades = state.get("trades", [])
        spend = state.get("spend", {})
    except Exception:
        trades = []
        spend = {}
    
    real_trades = [t for t in trades if t.get("mode") in ("real-auto", "real-micro")]
    paper_trades = [t for t in trades if t.get("mode") == "paper"]
    
    by_venue = {}
    for t in real_trades:
        for v in t.get("venues", []):
            by_venue.setdefault(v, {"count": 0, "size": 0})
            by_venue[v]["count"] += 1
            by_venue[v]["size"] += t.get("size", 0)
    
    return {
        "baseline": baseline,
        "trades_real": len(real_trades),
        "trades_paper": len(paper_trades),
        "spend_today": spend.get("amount", 0),
        "by_venue": by_venue,
        "recent_trades": real_trades[-10:]
    }

@app.post("/api/baseline/set")
async def api_baseline_set(request: Request):
    """Set baseline saldo untuk rekonsiliasi."""
    from app.baseline import save_baseline
    try:
        body = await request.json()
        save_baseline(body)
        return {"ok": True, "message": "baseline tersimpan"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/pnl")
def api_pnl():
    """P/L resolve-based: per venue + harian/mingguan/bulanan."""
    from datetime import datetime, timedelta
    try:
        from app.position_manager import load_positions
    except Exception:
        return {"by_venue": {}, "by_period": {}, "total_pnl": 0,
                "resolved_count": 0, "active_count": 0,
                "note": "position_manager belum tersedia"}
    positions = load_positions()
    resolved = [x for x in positions if x.get("resolved")]
    active = [x for x in positions if not x.get("resolved")]

    pnl_by_venue = {}
    for x in positions:
        v = x.get("venue", "?")
        d = pnl_by_venue.setdefault(v, {"count": 0, "invested": 0,
                                        "pnl_realized": 0, "active": 0})
        d["count"] += 1
        d["invested"] += x.get("size", 0)
        if x.get("resolved"):
            d["pnl_realized"] += x.get("pnl", 0)
        else:
            d["active"] += 1

    now = datetime.now()
    dk = lambda ts: (ts or "")[:10]
    today = now.strftime("%Y-%m-%d")
    week0 = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month0 = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    per = {}
    for x in resolved:
        v = x.get("venue", "?"); d = dk(x.get("resolved_ts"))
        row = per.setdefault(v, {"today": 0.0, "week": 0.0, "month": 0.0, "total": 0.0})
        row["total"] = round(row["total"] + x.get("pnl", 0), 2)
        if d == today: row["today"] = round(row["today"] + x.get("pnl", 0), 2)
        if d >= week0: row["week"] = round(row["week"] + x.get("pnl", 0), 2)
        if d >= month0: row["month"] = round(row["month"] + x.get("pnl", 0), 2)
    pt = sum(x.get("pnl", 0) for x in resolved if dk(x.get("resolved_ts")) == today)
    pw = sum(x.get("pnl", 0) for x in resolved if dk(x.get("resolved_ts")) >= week0)
    pm = sum(x.get("pnl", 0) for x in resolved if dk(x.get("resolved_ts")) >= month0)

    return {
        "by_venue": pnl_by_venue,
        "by_period": {"today": round(pt, 2), "week": round(pw, 2),
                      "month": round(pm, 2)},
        "total_pnl": round(sum(x.get("pnl", 0) for x in resolved), 2),
        "resolved_count": len(resolved),
        "active_count": len(active),
        "positions": positions[-20:],
        "by_venue_period": per,
    }


@app.post("/api/admin/reset-history")
def api_reset_history():
    """Bersihkan riwayat trades + spend untuk tampilan demo/serah terima."""
    import json as _json
    import time as _time
    from pathlib import Path as _P2
    sp = _P2("data/live_state.json")
    try:
        d = _json.loads(sp.read_text()) if sp.exists() else {}
    except Exception:
        d = {}
    bak = _P2("data/live_state.json.bak-history")
    bak.write_text(_json.dumps(d, indent=2))
    d["trades"] = []
    d["spend"] = {"today": _time.strftime("%Y-%m-%d"), "amount": 0.0}
    sp.write_text(_json.dumps(d, indent=2))
    return {"ok": True,
            "message": "riwayat trades + spend dibersihkan (backup: live_state.json.bak-history)"}


@app.post("/api/close-position")
async def api_close_position(request: Request):
    """Close posisi manual."""
    from app.executor import sell_kalshi, sell_polymarket, sell_limitless
    from app.config_store import load_creds
    from app.position_manager import load_positions, save_positions
    
    try:
        body = await request.json()
        venue = body.get("venue")
        position_id = body.get("position_id")
        size = float(body.get("size", 1))
        
        creds = load_creds().get(venue, {})
        positions = load_positions()
        pos = next((p for p in positions if p.get("market_id") == position_id and not p.get("resolved")), None)
        
        if not pos:
            # fallback: order manual tidak tercatat di buku posisi;
            # untuk Kalshi title == ticker, jadi bisa sell langsung
            if venue == "kalshi":
                ok2, msg2 = sell_kalshi(creds, position_id, "yes", size)
                return {"ok": ok2, "message": msg2}
            if venue == "polymarket":
                from app.venue_positions import get_positions_detailed
                rows = get_positions_detailed("polymarket", creds)
                _norm = lambda s: (s or "").strip().lower()
                hit = next((r for r in rows
                            if _norm(r.get("title")) == _norm(position_id)), None)
                if hit is None and rows:
                    return {"ok": False,
                            "message": "judul tidak cocok; tersedia di exchange: " +
                                       " | ".join((r.get("title") or "?") for r in rows)[:220]}
                if hit and hit.get("token_id"):
                    px = round(max((hit.get("cur_price") or 0.5) - 0.03, 0.01), 2)
                    ok2, msg2 = sell_polymarket(creds, hit["token_id"],
                                                hit.get("size") or size, px)
                    return {"ok": ok2, "message": msg2}
                return {"ok": False, "message": "posisi polymarket tidak ditemukan di exchange"}
            return {"ok": False,
                    "message": "posisi tidak ada di buku posisi; untuk venue ini tutup via web exchange"}
        
        ok, msg = False, "venue not supported"
        if venue == "kalshi":
            ok, msg = sell_kalshi(creds, position_id, "yes", size)
        elif venue == "polymarket":
            ok, msg = sell_polymarket(creds, position_id, "YES", size)
        elif venue == "limitless":
            ok, msg = sell_limitless(creds, position_id, size)
        
        if ok:
            pos["resolved"] = True
            pos["resolved_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            pos["manual_close"] = True
            save_positions(positions)
        
        return {"ok": ok, "message": msg}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/unrealized")
def api_unrealized():
    """Posisi aktif + unrealized P/L langsung dari exchange."""
    from app.venue_positions import get_positions_detailed
    from app.config_store import load_creds
    creds = load_creds()
    out = {}
    for v in ("polymarket", "kalshi", "limitless"):
        try:
            rows = get_positions_detailed(v, creds.get(v, {}))
            out[v] = [{"title": r.get("title"), "size": r.get("size"),
                       "value": r.get("value"), "pnl": r.get("pnl", 0),
                       "pnl_pct": r.get("pnl_pct", 0)} for r in rows]
        except Exception:
            out[v] = []
    try:
        ko = api_open_orders()
        for o in (ko.get("kalshi") or []):
            out.setdefault("kalshi", []).append({
                "title": o.get("ticker") or "?", "size": o.get("count") or 0,
                "value": 0.0, "pnl": 0.0, "pnl_pct": 0.0,
                "note": "open order menunggu fill"})
        for o in (ko.get("limitless") or []):
            out.setdefault("limitless", []).append({
                "title": o.get("ticker") or o.get("msg") or "?", "size": o.get("size") or 0,
                "value": 0.0, "pnl": 0.0, "pnl_pct": 0.0,
                "note": "open order menunggu fill"})
    except Exception:
        pass
    return out


@app.get("/api/open-orders")
def api_open_orders():
    """Open orders (menunggu fill) per venue."""
    import json as _j
    import base64 as _b64
    import time as _t
    from pathlib import Path as _P
    from app.config_store import load_creds
    out = {"kalshi": [], "limitless": []}
    creds = load_creds()
    try:
        import httpx
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        c = creds.get("kalshi", {})
        key_id = c.get("api_key_id", ""); pem = (c.get("private_key_pem") or "").strip()
        if key_id and "-----BEGIN" in pem:
            base = (c.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
            ts = str(int(_t.time() * 1000)); path = "/trade-api/v2/portfolio/orders"
            msg = f"{ts}GET{path}".encode()
            key = serialization.load_pem_private_key(pem.encode(), password=None)
            sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                           salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
            r = httpx.get(base + path, headers={
                "KALSHI-ACCESS-KEY": key_id,
                "KALSHI-ACCESS-SIGNATURE": _b64.b64encode(sig).decode(),
                "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
            orders = r.json().get("orders", [])
            out["kalshi"] = [{"order_id": o.get("order_id"), "ticker": o.get("ticker"),
                              "side": o.get("side"), "count": o.get("count"),
                              "price": o.get("price"),
                              "status": o.get("status")} for o in orders
                             if (o.get("status") or "resting") not in ("closed", "cancelled", "matched", "filled")]
    except Exception as e:
        out["kalshi_error"] = str(e)[:80]
    try:
        f = _P("data/manual_orders.json")
        mo = _j.loads(f.read_text()) if f.exists() else []
        out["limitless"] = [m for m in mo if m.get("venue") == "limitless" and not m.get("cancelled")]
    except Exception:
        pass
    return out


@app.post("/api/cancel-order")
async def api_cancel_order(request: Request):
    """Cancel open order."""
    import base64 as _b64
    import time as _t
    from app.config_store import load_creds
    body = await request.json()
    venue = body.get("venue"); oid = body.get("order_id")
    creds = load_creds()
    if venue == "kalshi":
        try:
            import json as _j
            import httpx
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            c = creds.get("kalshi", {})
            key_id = c.get("api_key_id", ""); pem = (c.get("private_key_pem") or "").strip()
            if not key_id or "-----BEGIN" not in pem:
                return {"ok": False, "message": "kredensial Kalshi tidak lengkap"}
            key = serialization.load_pem_private_key(pem.encode(), password=None)
            ticker = (body.get("ticker") or "").strip()
            last = ""
            for host in ("https://external-api.kalshi.com",
                         "https://api.elections.kalshi.com"):
                pathq = f"/trade-api/v2/portfolio/events/orders/{oid}"
                signpath = pathq
                if ticker:
                    pathq += f"?market_ticker={ticker}"
                ts = str(int(_t.time() * 1000))
                sig = key.sign(f"{ts}DELETE{signpath}".encode(),
                               padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                           salt_length=padding.PSS.DIGEST_LENGTH),
                               hashes.SHA256())
                r = httpx.delete(host + pathq, headers={
                    "KALSHI-ACCESS-KEY": key_id,
                    "KALSHI-ACCESS-SIGNATURE": _b64.b64encode(sig).decode(),
                    "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
                if r.status_code in (200, 204):
                    return {"ok": True, "message": f"order Kalshi {oid} dibatalkan"}
                last += f" | single {r.status_code}: {r.text[:120]}"
                pb = "/trade-api/v2/portfolio/events/orders/batched"
                ts = str(int(_t.time() * 1000))
                sigb = key.sign(f"{ts}DELETE{pb}".encode(),
                                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                            salt_length=padding.PSS.DIGEST_LENGTH),
                                hashes.SHA256())
                item = {"order_id": oid}
                if ticker:
                    item["market_ticker"] = ticker
                rb = httpx.request("DELETE", host + pb, headers={
                    "KALSHI-ACCESS-KEY": key_id,
                    "KALSHI-ACCESS-SIGNATURE": _b64.b64encode(sigb).decode(),
                    "KALSHI-ACCESS-TIMESTAMP": ts,
                    "Content-Type": "application/json"},
                    content=_j.dumps({"orders": [item]}), timeout=15)
                last += f" | batched {rb.status_code}: {rb.text[:120]}"
            # VERIFIKASI: order harus benar-benar hilang dari daftar resting
            try:
                ts = str(int(_t.time() * 1000)); pl = "/trade-api/v2/portfolio/orders"
                sigl = key.sign(f"{ts}GET{pl}".encode(),
                                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                            salt_length=padding.PSS.DIGEST_LENGTH),
                                hashes.SHA256())
                rl = httpx.get("https://api.elections.kalshi.com" + pl, headers={
                    "KALSHI-ACCESS-KEY": key_id,
                    "KALSHI-ACCESS-SIGNATURE": _b64.b64encode(sigl).decode(),
                    "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
                still = [o for o in (rl.json().get("orders") or [])
                         if o.get("order_id") == oid]
                if not still:
                    return {"ok": True,
                            "message": f"order Kalshi {oid} dibatalkan (terverifikasi)"}
                last += " | verifikasi: order masih ada"
            except Exception as ex:
                last += f" | verifikasi err: {ex}"
            return {"ok": False, "message": f"Kalshi cancel {last}"}
        except Exception as ex:
            return {"ok": False, "message": f"Kalshi cancel err: {ex}"}
    elif venue == "limitless":
        try:
            import json as _j
            from pathlib import Path as _P
            from app.executor import reap_limitless_stale
            f = _P("data/manual_orders.json")
            mo = _j.loads(f.read_text()) if f.exists() else []
            for m in mo:
                if m.get("order_id") == oid:
                    m["cancelled"] = True
            f.write_text(_j.dumps(mo, indent=2))
            count, tickers, err = reap_limitless_stale()
            return {"ok": True, "message": f"order Limitless ditandai batal; reaper cancel {count}"}
        except Exception as e:
            return {"ok": False, "message": str(e)[:100]}
    return {"ok": False, "message": "venue tidak didukung"}
