# /app/engine.py
"""Engine S3: match lintas venue + Π, eksekusi PAPER. REAL = S4."""
import json
import re
import threading
import time
from pathlib import Path

from app.config_store import load_config, load_creds, MIN_ORDER_USD
from app.alert import dispatch_alert
from app.venue_markets import FETCH, _poly_events, _kalshi_events
from app.executor import EXEC

# === Path & Konstanta ===
SESSION = Path("data") / "session.json"
STATE = Path("data") / "live_state.json"
KILL = Path("data") / "kill.json"
LOOP_LOG = Path("data") / "engine_loop.log"

FEES = {"polymarket": 0.0, "kalshi": 0.04, "limitless": 0.004}
INTERVAL = 30
SCAN_EVERY_SEC = 120

_thr = None
_run = False
_wd_on = False
_last_scan_ts = 0.0

STOP = set("on in by at will the of for a an or and to with from be is above "
           "below up down hit close end before after".split())

SYN = {"bitcoin": "btc", "ethereum": "eth", "solana": "sol",
       "dogecoin": "doge", "bnb": "bnb", "xrp": "xrp"}

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
          "august": 8, "september": 9, "october": 10}

REAPER_EVERY_SEC = 300
_last_reaper_ts = 0.0
ALERT_CHECK_SEC = 60
_last_alert_ts = 0.0


# === Helper Sesi ===
def _start_session(mode):
    SESSION.parent.mkdir(exist_ok=True)
    SESSION.write_text(json.dumps(
        {"mode": mode, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}))


def _session_mode():
    if SESSION.exists():
        try:
            return json.loads(SESSION.read_text()).get("mode")
        except Exception:
            pass
    return None


# === Parser Angka & Matching ===
def _num(s):
    s = s.replace(",", "").replace("$", "").strip()
    if s.endswith("k"):
        return float(s[:-1]) * 1000
    return float(s)


def crypto_key(t):
    """Kunci struktural: aset-strike-tanggal (tahan beda gaya judul)."""
    t = (t or "").lower()
    asset = None
    for pat, a in [(r"\b(btc|bitcoin)\b", "btc"), (r"\b(eth|ethereum)\b", "eth"),
                   (r"\b(sol|solana)\b", "sol"), (r"\b(doge|dogecoin)\b", "doge")]:
        if re.search(pat, t):
            asset = a
            break
    if not asset:
        return None
    m = re.search(r"\$?\s*(\d[\d,\.]*\s*k?)", t)
    strike = None
    if m:
        try:
            strike = _num(m.group(1))
        except Exception:
            strike = None
    mo = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
                   r"august|september|october)\w*\s+(\d{1,2})\b", t)
    if strike is None or not mo:
        return None
    return f"{asset}-{strike:.0f}-{MONTHS.get(mo.group(1))}-{mo.group(2)}"


def _tok(t):
    out = set()
    for w in re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split():
        if w not in STOP:
            out.add(SYN.get(w, w))
    return out


def sim(a, b):
    ta, tb = _tok(a), _tok(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


# === State I/O dengan Lock (Thread-Safe) ===
_state_lock = threading.Lock()
_scan_lock = threading.Lock()


def _read():
    """Baca state dari disk, thread-safe."""
    with _state_lock:
        try:
            st = json.loads(STATE.read_text()) if STATE.exists() else {}
        except Exception:
            st = {}
        if not st.get("limits"):
            try:
                cfg = json.loads(pathlib.Path("data/trading_config.json").read_text())
                st["limits"] = cfg.get("limits", {})
            except Exception:
                st["limits"] = {}
        return st


def _write(st):
    """Tulis state ke disk, thread-safe."""
    with _state_lock:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=2, default=str))


# === Loop Logging ===
def _log_loop(msg: str):
    try:
        LOOP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOOP_LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
    except Exception:
        pass


# === Scan Shared (Mutex) ===
_FBCACHE = {}


def _scan_shared():
    global _last_scan_ts
    with _scan_lock:
        _log_loop("scan start")
        out = _scan()
        _last_scan_ts = time.time()
        _log_loop(f"scan finish: {len(out[0])} matches")
        return out


import datetime as _dtc
def _close_ts(title, now=None):
    """Perkiraan timestamp resolusi dari pola jendela waktu di judul (epoch-aligned)."""
    s = (title or "").lower()
    now = now or time.time()
    if "5 min" in s or "5-min" in s:
        step = 300
    elif "15 min" in s or "15-min" in s:
        step = 900
    elif "hourly" in s or "1 hour" in s:
        step = 3600
    elif "daily" in s or "24 hour" in s:
        step = 86400
    elif "weekly" in s:
        step = 7 * 86400
    else:
        return None
    return int(now // step) * step + step


_CKSYN = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana", "doge": "dogecoin",
          "xrp": "ripple", "bnb": "binance", "bch": "bitcoin-cash", "ltc": "litecoin"}


_CKPAT = (("bitcoin", "bitcoin"), ("btc", "bitcoin"), ("ethereum", "ethereum"), ("eth", "ethereum"),
          ("solana", "solana"), ("sol", "solana"), ("dogecoin", "dogecoin"), ("doge", "dogecoin"),
          ("xrp", "ripple"), ("bnb", "binance"), ("litecoin", "litecoin"), ("ltc", "litecoin"))


def _ckey(title):
    k = crypto_key(title)
    if k:
        return _CKSYN.get(k, k)
    import re as _rek
    s = (title or "").lower()
    for pat, canon in _CKPAT:
        if _rek.search(r"\b" + pat + r"\b", s):
            return canon
    return None


def _wstep(title):
    s = (title or "").lower()
    if "5 min" in s or "5-min" in s:
        return 300
    if "15 min" in s or "15-min" in s:
        return 900
    if "hourly" in s or "1 hour" in s:
        return 3600
    if "daily" in s or "24 hour" in s:
        return 86400
    if "weekly" in s:
        return 7 * 86400
    return None


def _row_end(row):
    return row.get("end_ts") or _close_ts(row.get("title"))


_PAIR_COUNT = {}


def _scan():
    """Scan semua venue, cari match lintas venue dengan rumus YES+NO arbitrage."""
    cfg = load_config()
    creds = load_creds()
    pairs = cfg.get("pairs", {})
    venues = [v for v, s in cfg["venues"].items()
              if s.get("valid") and s.get("enabled") and pairs.get(v)]

    log = []
    def L(msg):
        log.append(f"{time.strftime('%H:%M:%S')} {msg}")

    rows = {}
    for v in venues:
        ev_rows = []
        try:
            if v == "polymarket":
                ev_rows = _poly_events(creds.get(v, {}))
            elif v == "kalshi":
                ev_rows = _kalshi_events(creds.get(v, {}))
        except Exception:
            ev_rows = []
        ev_rows = [r for r in ev_rows if r["cat"] in pairs[v]]
        if len(ev_rows) >= 1:
            rows[v] = ev_rows
        else:
            try:
                _fb = _FBCACHE.get(v)
                if _fb and time.time() - _fb[1] < 240:
                    allr = _fb[0]
                else:
                    allr = FETCH[v](creds.get(v, {}))
                    _FBCACHE[v] = (allr, time.time())
            except Exception:
                allr = []
            rows[v] = sorted((r for r in allr if r["cat"] in pairs[v]), key=lambda r: -(r.get("vol") or 0))[:150]
        L(f"fetch {v} → {len(rows[v])} event")

    t0 = time.time()
    comparisons = 0
    matches = []
    near = []
    vs = list(rows)
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            a, b = vs[i], vs[j]
            n_pair = 0
            for ma in rows[a][:150]:
                ka = _ckey(ma["title"]) if ma["cat"] == "crypto" else None
                for mb in rows[b][:150]:
                    if ma["cat"] != mb["cat"]:
                        continue
                    comparisons += 1
                    n_pair += 1
                    kb = _ckey(mb["title"]) if mb["cat"] == "crypto" else None
                    s = sim(ma["title"], mb["title"])
                    if ma["cat"] == "crypto":
                        same = bool(ka and kb and ka == kb and _row_end(ma) is not None and _row_end(ma) == _row_end(mb) and _wstep(ma["title"]) == _wstep(mb["title"]))
                        if (not same) and (ma["cat"] != mb["cat"] or _wstep(ma["title"]) != _wstep(mb["title"])):
                            _ea, _eb = _row_end(ma), _row_end(mb)
                            if _ea and _ea == _eb:
                                _ya, _yb = ma.get("yes") or 0.0, mb.get("yes") or 0.0
                                if 0.01 < _ya < 0.99 and 0.01 < _yb < 0.99:
                                    _f2 = FEES[a] + FEES[b]
                                    _mc2 = min(_ya + (1 - _yb), (1 - _ya) + _yb)
                                    _pi2 = round((1.0 - _mc2) - _f2, 4)
                                    if -0.30 < _pi2 < 0.30 and sum(1 for _x in matches if _x.get("locked") is False) < 6:
                                        matches.append({"a": a, "b": b, "cat": ma["cat"] + "+" + mb["cat"],
                                                        "ta": ma["title"], "tb": mb["title"],
                                                        "gross": round(1.0 - _mc2, 4), "fees": _f2,
                                                        "pi": _pi2, "direction": "CROSS_CAT",
                                                        "leg_a_side": "YES", "leg_b_side": "NO",
                                                        "locked": False, "ea": _ea, "eb": _eb})
                    else:
                        same = s >= 0.65

                    if not same:
                        if s >= 0.25:
                            # Guard entitas: wajib ada token bersama (negara/ticker/objek)
                            import re as _re
                            _syn = {"btc":"bitcoin","eth":"ethereum","sol":"solana","doge":"dogecoin","xrp":"ripple","bnb":"binance"}
                            _stop = set(("who what when where will the of after before next be to in on for and or a an by from vs hit above below up down price week month daily hourly minute min year day open close higher lower reach at end between than more less over under once ever win host champion become which how many is it its this that with without during through per each any some all no yes not new old first last final round match game team player score points total number count rate cut hike decision meeting announce official confirmed winner candidate nominee party vote votes poll polls election elections prime minister ministers president presidential king queen leader leaders win wins won lose loses lost beat beats defeat defeats championship champion champions cup cups league leagues series world national international global local regional state states country countries city cities get gets got go goes gone went come comes came make makes made take takes took taken see sees saw seen know knows knew known think thinks thought believe believes believed say says said tell tells told ask asks asked").split())
                            def _toks(s):
                                return {_syn.get(w, w) for w in _re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and _syn.get(w, w) not in _stop}
                            if not (_toks(ma["title"]) & _toks(mb["title"])):
                                continue
                            near.append({"a": a, "b": b, "s": round(s, 2),
                                         "ta": ma["title"][:40],
                                         "tb": mb["title"][:40]})
                            L(f"kandidat {a}×{b} sim {s:.2f}: "
                              f"{ma['title'][:28]} ↔ {mb['title'][:28]}")
                        continue

                    ya = ma.get("yes") or 0.0
                    yb = mb.get("yes") or 0.0

                    # === RUMUS ARBITRASE YES+NO (KLASIK) ===
                    if ya > 0.01 and ya < 0.99 and yb > 0.01 and yb < 0.99:
                        fees = FEES[a] + FEES[b]
                        cost_yes_no = ya + (1 - yb)  # YES di A, NO di B
                        cost_no_yes = (1 - ya) + yb  # NO di A, YES di B
                        min_cost = min(cost_yes_no, cost_no_yes)
                        pi = round((1.0 - min_cost) - fees, 4)

                        if cost_yes_no <= cost_no_yes:
                            direction = "YES_NO"
                            leg_a_side, leg_b_side = "YES", "NO"
                        else:
                            direction = "NO_YES"
                            leg_a_side, leg_b_side = "NO", "YES"

                        gross = round(1.0 - min_cost, 4)
                    else:
                        # Fallback spread-based bila harga tidak valid
                        spread = max(yb - ya, ya - yb) if (ya > 0 and yb > 0) else 0.0
                        fees = FEES[a] + FEES[b]
                        pi = round(spread - fees, 4)
                        direction = "SPREAD"
                        leg_a_side, leg_b_side = "YES", "YES"
                        gross = round(spread, 4)

                    # Pagar anti false-match (Π > 20% = pasti salah pasang)
                    if pi > 0.10:
                        L(f"SKIP Π terlalu tinggi {pi*100:.1f}¢: "
                          f"{ma['title'][:28]} ↔ {mb['title'][:28]}")
                        continue

                    matches.append({
                        "a": a, "b": b, "cat": ma["cat"],
                        "ta": ma["title"], "tb": mb["title"],
                        "gross": gross,
                        "fees": round(fees, 4),
                        "pi": pi,
                        "direction": direction,
                        "leg_a_side": leg_a_side,
                        "leg_b_side": leg_b_side,
                        "ea": _row_end(ma), "eb": _row_end(mb)
                    })
                    L(f"MATCH {a}×{b} {direction} Π {pi*100:.1f}¢: "
                      f"{ma['title'][:28]} ↔ {mb['title'][:28]}")
            L(f"banding {a}×{b}: {n_pair} pairs")
    near.sort(key=lambda x: -x["s"])
    matches.sort(key=lambda m: -m["pi"])
    L(f"selesai: {comparisons} perbandingan · {len(matches)} match · "
      f"{round(time.time()-t0,1)} dtk")
    info = {"counts": {v: len(rows[v]) for v in rows},
            "comparisons": comparisons,
            "ts": time.strftime("%H:%M:%S"),
            "epoch": int(time.time()),
            "duration": round(time.time() - t0, 1)}
    return matches[:10], info, near[:5], log[-150:]


# === Main Loop ===


def _auto_take_profit():
    """Auto-sell posisi bila untung >= tp%."""
    from app.venue_positions import get_positions_detailed
    from app.executor import sell_kalshi
    from app.position_manager import load_positions, save_positions
    
    cfg = load_config()
    tp_pct = float(cfg.get("limits", {}).get("tp", 10)) / 100
    positions = load_positions()
    active = [p for p in positions if not p.get("resolved")]
    
    if not active:
        return 0
    
    creds = load_creds()
    closed_count = 0
    
    for pos in active:
        venue = pos.get("venue")
        buy_price = pos.get("buy_price", 0)
        size = pos.get("size", 0)
        buy_value = buy_price * size
        target = buy_value * (1 + tp_pct)
        
        try:
            current_positions = get_positions_detailed(venue, creds.get(venue, {}))
            current = next((p for p in current_positions 
                          if p.get("title") == pos.get("market_id")), None)
            if not current:
                continue
            
            current_value = current.get("value", 0)
            if current_value >= target and current_value > buy_value:
                # Auto-sell
                ok, msg = False, "venue not supported"
                if venue == "kalshi":
                    ticker = current.get("ticker") or pos.get("market_id")
                    side = current.get("side", "yes")
                    ok, msg = sell_kalshi(creds.get(venue, {}), ticker, side, size)
                
                if ok:
                    pos["resolved"] = True
                    pos["pnl"] = round(current_value - buy_value, 2)
                    pos["resolved_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    pos["auto_tp"] = True
                    closed_count += 1
                    _log_loop(f"auto-tp: {venue} {pos.get('market_id')} P/L=${pos['pnl']:.2f}")
        except Exception as e:
            _log_loop(f"auto-tp error: {venue} {e}")
    
    if closed_count > 0:
        save_positions(positions)
    
    return closed_count
def _loop():
    
    global _run, _PAIR_COUNT, _last_scan_ts, _last_reaper_ts, _last_alert_ts
#     was_real = _session_mode() == "real"
#     if SESSION.exists():
#         SESSION.unlink()
#     _run = False
#     st = _read()
#     st["running"] = False
#     if was_real:
#         st["need_rearm"] = True
#     _write(st)
#     _log_loop("engine stopped")


# def kill():
#     """Kill switch — hentikan permanen."""
#     stop()
#     st = _read()
#     st["need_rearm"] = True
#     _write(st)
#     KILL.parent.mkdir(exist_ok=True)
#     KILL.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}))
#     _log_loop("kill switch activated")


# def unkill():
#     """Buka kill switch."""
#     if KILL.exists():
#         KILL.unlink()
#     st = _read()
#     st.pop("need_rearm", None)
#     st.pop("auto_stop", None)
#     _write(st)
#     _log_loop("kill switch cleared")


# # === Mikro Eksekusi Manual ===
# def micro_exec(venue, dry=False):
#     """Eksekusi manual satu order (tombol 🎯)."""
#     if KILL.exists():
#         return {"ok": False, "message": "kill switch aktif — eksekusi ditolak"}
#     cfg = load_config()
#     lim = cfg.get("limits", {})
#     per_op = float(lim.get("modal_per_op", 2))
#     st = _read()

#     today = time.strftime("%Y-%m-%d")
#     sp = st.get("spend", {})
#     if sp.get("today") != today:
#         sp = {"today": today, "amount": 0.0}
#     cap = float(lim.get("rugi_harian", 5))
#     if not dry and sp["amount"] + per_op > cap:
#         return {"ok": False,
#                 "message": f"cap harian tercapai (${sp['amount']:.2f}/${cap:.2f}) "
#                            f"— berlaku global semua venue; naikkan di /limits "
#                            f"atau reset harian"}

#     fn = EXEC.get(venue)
#     if not fn:
#         return {"ok": False, "message": "venue tidak dikenal"}
#     _usd = max(per_op, MIN_ORDER_USD.get(venue, 0.0))
#     ok, msg = fn(load_creds().get(venue, {}), usd=_usd, dry=dry)

#     if ok and not dry:
#         sp["amount"] = round(sp["amount"] + per_op, 2)
#         st["spend"] = sp
#         st.setdefault("trades", []).append({
#             "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "real-micro",
#             "venues": [venue], "pi": 0.0, "size": per_op, "note": msg[:60]})
#         st["trades"] = st["trades"][-10000:]
#         _write(st)
#     return {"ok": ok, "message": msg}


# # === Status ===
# def status():
#     """Kembalikan status engine."""
#     st = _read()
#     st["running"] = bool(_run)
#     st["kill"] = KILL.exists()
#     st["session"] = _session_mode()
#     return st

