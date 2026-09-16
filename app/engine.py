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
            if STATE.exists():
                return json.loads(STATE.read_text())
        except Exception:
            pass
        return {}


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
def _scan_shared():
    global _last_scan_ts
    with _scan_lock:
        _log_loop("scan start")
        out = _scan()
        _last_scan_ts = time.time()
        _log_loop(f"scan finish: {len(out[0])} matches")
        return out


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
        if len(ev_rows) >= 5:
            rows[v] = ev_rows
        else:
            try:
                allr = FETCH[v](creds.get(v, {}))
            except Exception:
                allr = []
            rows[v] = [r for r in allr if r["cat"] in pairs[v]]
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
            for ma in rows[a][:60]:
                ka = crypto_key(ma["title"]) if ma["cat"] == "crypto" else None
                for mb in rows[b][:60]:
                    if ma["cat"] != mb["cat"]:
                        continue
                    comparisons += 1
                    n_pair += 1
                    kb = crypto_key(mb["title"]) if mb["cat"] == "crypto" else None
                    s = sim(ma["title"], mb["title"])
                    if ma["cat"] == "crypto":
                        same = bool(ka and kb and ka == kb)
                    else:
                        same = s >= 0.5

                    if not same:
                        if s >= 0.25:
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
                    if pi > 0.20:
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
                        "leg_b_side": leg_b_side
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
def _loop():
    """Loop eksekusi keputusan (paper/real)."""
    global _run, _last_reaper_ts, _last_alert_ts
    errs = 0
    _log_loop("loop start")
    while _run:
        t0 = time.time()
        try:
            cfg = load_config()
            st = _read()
            st["running"] = True
            if (time.time() - _last_scan_ts >= SCAN_EVERY_SEC) or not st.get("matches"):
                st["matches"], st["info"], st["near"], st["scanlog"] = _scan_shared()
                st["interval"] = INTERVAL

            # === REAPER: auto-cancel order Limitless GTC ===
            if time.time() - _last_reaper_ts >= REAPER_EVERY_SEC:
                _last_reaper_ts = time.time()
                try:
                    from app.executor import reap_limitless_stale
                    count, tickers, err = reap_limitless_stale()
                except Exception as reaper_exc:
                    _log_loop(f"reaper exception: {type(reaper_exc).__name__}: {reaper_exc}")
                    count, tickers, err = 0, [], None

                if count > 0:
                    _log_loop(f"reaper: cancelled {count} stale orders: {tickers}")
                    st.setdefault("trades", []).append({
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "mode": "cancel-auto",
                        "venues": ["limitless"],
                        "pi": 0.0,
                        "size": 0.0,
                        "note": f"cancelled {count} stale GTC orders: {', '.join(str(x) for x in tickers[:3])}"
                    })
                    st["trades"] = st["trades"][-50:]
                elif err:
                    _log_loop(f"reaper: {err}")
                else:
                    _log_loop("reaper: skip (no open orders)")

            # === AUTO-CLOSE: cek posisi yang sudah resolve ===
            try:
                from app.position_manager import check_and_close_positions
                check_and_close_positions()
            except ImportError:
                pass  # position_manager belum ada, skip
            except Exception as pos_exc:
                _log_loop(f"position check exception: {type(pos_exc).__name__}: {pos_exc}")

            # === ALERT CHECK: pantau kondisi kritis tiap 60 detik ===
            if time.time() - _last_alert_ts >= ALERT_CHECK_SEC:
                _last_alert_ts = time.time()
                if st.get("auto_stop"):
                    dispatch_alert("critical", f"Engine auto-stop: {st['auto_stop']}", "auto_stop")
                if st.get("last_error"):
                    dispatch_alert("warning", f"Loop error: {st['last_error']}", "last_error")
                if _run and _thr is not None and not _thr.is_alive():
                    dispatch_alert("critical", "Loop thread mati, watchdog gagal respawn", "thread_dead")

            # === EKSEKUSI KEPUTUSAN ===
            lim = cfg.get("limits", {})
            minp = float(lim.get("min_profit", 0.5)) / 100
            per_op = float(lim.get("modal_per_op", 2))
            cap = float(lim.get("rugi_harian", 5))

            today = time.strftime("%Y-%m-%d")
            sp = st.get("spend", {})
            if sp.get("today") != today:
                sp = {"today": today, "amount": 0.0}

            added = 0
            for m in st["matches"]:
                if m["pi"] < minp:
                    continue
                if st.get("mode") == "real" and sp["amount"] + per_op <= cap:
                    # MODE ARBITRASE KLASIK: YES+NO (dua kaki berlawanan arah)
                    leg_a_side = m.get("leg_a_side", "YES")
                    leg_b_side = m.get("leg_b_side", "YES")
                    legs = [(m["a"], leg_a_side), (m["b"], leg_b_side)]
                    for venue, side in legs:
                        fn = EXEC.get(venue)
                        if not fn:
                            continue
                        _usd = max(per_op, MIN_ORDER_USD.get(venue, 0.0))
                        try:
                            ok, msg = fn(load_creds().get(venue, {}), usd=_usd, side=side)
                        except TypeError:
                            # Executor lama belum support side
                            try:
                                ok, msg = fn(load_creds().get(venue, {}), usd=_usd)
                            except Exception:
                                ok, msg = False, "executor exception"
                        except Exception:
                            ok, msg = False, "executor exception"
                        if ok:
                            sp["amount"] = round(sp["amount"] + per_op, 2)
                            st.setdefault("trades", []).append({
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "mode": "real-auto", "venues": [venue],
                                "pi": m["pi"], "size": per_op,
                                "direction": m.get("direction", "SPREAD"),
                                "note": msg[:60]})
                            st["trades"] = st["trades"][-50:]
                            added += 1

                            # Track posisi untuk auto-close + P/L
                            try:
                                from app.position_manager import track_new_position
                                track_new_position(
                                    venue=venue,
                                    market_id=m.get("ta", "")[:60],
                                    buy_price=m.get("gross", 0) / 2,
                                    size=per_op,
                                    direction=m.get("direction", "SPREAD")
                                )
                            except ImportError:
                                pass
                else:
                    st.setdefault("trades", []).append({
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "mode": st.get("mode", "paper"),
                        "venues": [m["a"], m["b"]], "pi": m["pi"], "size": per_op,
                        "direction": m.get("direction", "SPREAD")})
                    st["trades"] = st["trades"][-50:]
                    added += 1

            st["spend"] = sp
            errs = 0
            st.pop("last_error", None)

            if sp["amount"] >= cap:
                st["auto_stop"] = (f"{time.strftime('%H:%M:%S')} "
                                   f"cap rugi harian tercapai ${sp['amount']:.2f}")
                _write(st)
                _log_loop("auto-stop cap harian")
                stop()
                break
            _write(st)
            _log_loop(f"cycle ok matches={len(st.get('matches') or [])} +trades={added}")
            time.sleep(max(5, INTERVAL - (time.time() - t0)))
        except Exception as e:
            errs += 1
            _log_loop(f"cycle error {type(e).__name__}: {e}")
            st = _read()
            st["last_error"] = f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {e}"
            if errs >= 5:
                st["auto_stop"] = (f"{time.strftime('%H:%M:%S')} "
                                   f"5 error beruntun: {type(e).__name__}")
                _write(st)
                _log_loop("auto-stop 5 error")
                stop()
                break
            _write(st)
            time.sleep(5)
    _log_loop("loop exit")


# === Refresh untuk Dashboard ===
def refresh():
    """Scan baru sekarang juga (dipakai saat halaman dashboard dibuka)."""
    if KILL.exists() or not _run:
        return status()
    st = _read()
    # Scan HANYA dari loop engine (thread terpisah).
    # refresh() tidak boleh memperebutkan _scan_lock, agar event-loop server
    # tidak terkunci dan request dashboard tetap lancar saat scan berjalan.
    st["interval"] = INTERVAL
    _write(st)
    return st


# === Watchdog ===
def _watchdog():
    """Pastikan thread loop tetap hidup."""
    global _thr
    while True:
        time.sleep(20)
        try:
            if _run and (_thr is None or not _thr.is_alive()):
                _log_loop("watchdog: respawn loop")
                _thr = threading.Thread(target=_loop, daemon=True)
                _thr.start()
        except Exception:
            pass


# === Kontrol Engine ===
def start(mode):
    """Mulai engine (paper/real)."""
    global _thr, _run, _wd_on
    if KILL.exists():
        return False, "kill switch aktif — buka kunci dulu"
    if _run:
        current = st.get("mode", "unknown") if (st := _read()) else "unknown"
        return False, f"sudah berjalan dalam mode {current.upper()}. Klik Stop dulu, lalu Mulai {mode.capitalize()}."
    st = _read()
    st["mode"] = mode
    st.pop("auto_stop", None)
    _write(st)
    _start_session(mode)
    _run = True
    _thr = threading.Thread(target=_loop, daemon=True)
    _thr.start()
    if not _wd_on:
        _wd_on = True
        threading.Thread(target=_watchdog, daemon=True).start()
    _log_loop(f"engine started mode={mode}")
    return True, f"engine {mode} dimulai"


def stop():
    """Hentikan engine."""
    global _run
    was_real = _session_mode() == "real"
    if SESSION.exists():
        SESSION.unlink()
    _run = False
    st = _read()
    st["running"] = False
    if was_real:
        st["need_rearm"] = True
    _write(st)
    _log_loop("engine stopped")


def kill():
    """Kill switch — hentikan permanen."""
    stop()
    st = _read()
    st["need_rearm"] = True
    _write(st)
    KILL.parent.mkdir(exist_ok=True)
    KILL.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    _log_loop("kill switch activated")


def unkill():
    """Buka kill switch."""
    if KILL.exists():
        KILL.unlink()
    st = _read()
    st.pop("need_rearm", None)
    st.pop("auto_stop", None)
    _write(st)
    _log_loop("kill switch cleared")


# === Mikro Eksekusi Manual ===
def micro_exec(venue, dry=False):
    """Eksekusi manual satu order (tombol 🎯)."""
    if KILL.exists():
        return {"ok": False, "message": "kill switch aktif — eksekusi ditolak"}
    cfg = load_config()
    lim = cfg.get("limits", {})
    per_op = float(lim.get("modal_per_op", 2))
    st = _read()

    today = time.strftime("%Y-%m-%d")
    sp = st.get("spend", {})
    if sp.get("today") != today:
        sp = {"today": today, "amount": 0.0}
    cap = float(lim.get("rugi_harian", 5))
    if not dry and sp["amount"] + per_op > cap:
        return {"ok": False,
                "message": f"cap harian tercapai (${sp['amount']:.2f}/${cap:.2f}) "
                           f"— berlaku global semua venue; naikkan di /limits "
                           f"atau reset harian"}

    fn = EXEC.get(venue)
    if not fn:
        return {"ok": False, "message": "venue tidak dikenal"}
    _usd = max(per_op, MIN_ORDER_USD.get(venue, 0.0))
    ok, msg = fn(load_creds().get(venue, {}), usd=_usd, dry=dry)

    if ok and not dry:
        sp["amount"] = round(sp["amount"] + per_op, 2)
        st["spend"] = sp
        st.setdefault("trades", []).append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "real-micro",
            "venues": [venue], "pi": 0.0, "size": per_op, "note": msg[:60]})
        st["trades"] = st["trades"][-50:]
        _write(st)
    return {"ok": ok, "message": msg}


# === Status ===
def status():
    """Kembalikan status engine."""
    st = _read()
    st["running"] = bool(_run)
    st["kill"] = KILL.exists()
    st["session"] = _session_mode()
    return st

# =============================================================================================================
# # /app/engine.py
# """Engine S3: match lintas venue + Π, eksekusi PAPER. REAL = S4."""
# import json
# import re
# import threading
# import time
# from pathlib import Path

# from app.config_store import load_config, load_creds, MIN_ORDER_USD
# from app.alert import dispatch_alert
# from app.venue_markets import FETCH, _poly_events, _kalshi_events
# from app.executor import EXEC
# from app.position_manager import check_and_close_positions

# # === Path & Konstanta ===
# SESSION = Path("data") / "session.json"
# STATE = Path("data") / "live_state.json"
# KILL = Path("data") / "kill.json"
# LOOP_LOG = Path("data") / "engine_loop.log"

# FEES = {"polymarket": 0.0, "kalshi": 0.04, "limitless": 0.004}
# INTERVAL = 60
# SCAN_EVERY_SEC = 120

# _thr = None
# _run = False
# _wd_on = False
# _last_scan_ts = 0.0

# STOP = set("on in by at will the of for a an or and to with from be is above "
#            "below up down hit close end before after".split())

# SYN = {"bitcoin": "btc", "ethereum": "eth", "solana": "sol",
#        "dogecoin": "doge", "bnb": "bnb", "xrp": "xrp"}

# MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
#           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
#           "august": 8, "september": 9, "october": 10}

# REAPER_EVERY_SEC = 300
# _last_reaper_ts = 0.0
# ALERT_CHECK_SEC = 60
# _last_alert_ts = 0.0

# # Cek posisi resolve tiap 5 menit (sama dengan reaper)
# if time.time() - _last_reaper_ts >= REAPER_EVERY_SEC:
#     check_and_close_positions()
    
# # === Helper Sesi ===
# def _start_session(mode):
#     SESSION.parent.mkdir(exist_ok=True)
#     SESSION.write_text(json.dumps(
#         {"mode": mode, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}))


# def _session_mode():
#     if SESSION.exists():
#         try:
#             return json.loads(SESSION.read_text()).get("mode")
#         except Exception:
#             pass
#     return None


# # === Parser Angka & Matching ===
# def _num(s):
#     s = s.replace(",", "").replace("$", "").strip()
#     if s.endswith("k"):
#         return float(s[:-1]) * 1000
#     return float(s)


# def crypto_key(t):
#     """Kunci struktural: aset-strike-tanggal (tahan beda gaya judul)."""
#     t = (t or "").lower()
#     asset = None
#     for pat, a in [(r"\b(btc|bitcoin)\b", "btc"), (r"\b(eth|ethereum)\b", "eth"),
#                    (r"\b(sol|solana)\b", "sol"), (r"\b(doge|dogecoin)\b", "doge")]:
#         if re.search(pat, t):
#             asset = a
#             break
#     if not asset:
#         return None
#     m = re.search(r"\$?\s*(\d[\d,\.]*\s*k?)", t)
#     strike = None
#     if m:
#         try:
#             strike = _num(m.group(1))
#         except Exception:
#             strike = None
#     mo = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
#                    r"august|september|october)\w*\s+(\d{1,2})\b", t)
#     if strike is None or not mo:
#         return None
#     return f"{asset}-{strike:.0f}-{MONTHS.get(mo.group(1))}-{mo.group(2)}"


# def _tok(t):
#     out = set()
#     for w in re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split():
#         if w not in STOP:
#             out.add(SYN.get(w, w))
#     return out


# def sim(a, b):
#     ta, tb = _tok(a), _tok(b)
#     return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


# # === State I/O dengan Lock (Thread-Safe) ===
# _state_lock = threading.Lock()
# _scan_lock = threading.Lock()


# def _read():
#     """Baca state dari disk, thread-safe."""
#     with _state_lock:
#         try:
#             if STATE.exists():
#                 return json.loads(STATE.read_text())
#         except Exception:
#             pass
#         return {}


# def _write(st):
#     """Tulis state ke disk, thread-safe."""
#     with _state_lock:
#         STATE.parent.mkdir(parents=True, exist_ok=True)
#         STATE.write_text(json.dumps(st, indent=2, default=str))


# # === Loop Logging ===
# def _log_loop(msg: str):
#     try:
#         LOOP_LOG.parent.mkdir(parents=True, exist_ok=True)
#         with open(LOOP_LOG, "a") as f:
#             f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
#     except Exception:
#         pass


# # === Scan Shared (Mutex) ===
# def _scan_shared():
#     global _last_scan_ts
#     with _scan_lock:
#         out = _scan()
#         _last_scan_ts = time.time()
#         return out


# def _scan():
#     """Scan semua venue, cari match lintas venue."""
#     cfg = load_config()
#     creds = load_creds()
#     pairs = cfg.get("pairs", {})
#     venues = [v for v, s in cfg["venues"].items()
#               if s.get("valid") and s.get("enabled") and pairs.get(v)]

#     log = []
#     def L(msg):
#         log.append(f"{time.strftime('%H:%M:%S')} {msg}")

#     rows = {}
#     for v in venues:
#         ev_rows = []
#         try:
#             if v == "polymarket":
#                 ev_rows = _poly_events(creds.get(v, {}))
#             elif v == "kalshi":
#                 ev_rows = _kalshi_events(creds.get(v, {}))
#         except Exception:
#             ev_rows = []
#         ev_rows = [r for r in ev_rows if r["cat"] in pairs[v]]
#         if len(ev_rows) >= 5:
#             rows[v] = ev_rows
#         else:
#             try:
#                 allr = FETCH[v](creds.get(v, {}))
#             except Exception:
#                 allr = []
#             rows[v] = [r for r in allr if r["cat"] in pairs[v]]
#         L(f"fetch {v} → {len(rows[v])} event")

#     t0 = time.time()
#     comparisons = 0
#     matches = []
#     near = []
#     vs = list(rows)
#     for i in range(len(vs)):
#         for j in range(i + 1, len(vs)):
#             a, b = vs[i], vs[j]
#             n_pair = 0
#             for ma in rows[a][:60]:
#                 ka = crypto_key(ma["title"]) if ma["cat"] == "crypto" else None
#                 for mb in rows[b][:60]:
#                     if ma["cat"] != mb["cat"]:
#                         continue
#                     comparisons += 1
#                     n_pair += 1
#                     kb = crypto_key(mb["title"]) if mb["cat"] == "crypto" else None
#                     # s = sim(ma["title"], mb["title"])
#                     # same = (ka and ka == kb) or s >= 0.5

#                     s = sim(ma["title"], mb["title"])
#                     if ma["cat"] == "crypto":
#                         same = bool(ka and kb and ka == kb)   # crypto wajib kunci struktural sama
#                     else:
#                         same = s >= 0.5
                        
#                     if not same:
#                         if s >= 0.25:
#                             near.append({"a": a, "b": b, "s": round(s, 2),
#                                          "ta": ma["title"][:40],
#                                          "tb": mb["title"][:40]})
#                             L(f"kandidat {a}×{b} sim {s:.2f}: "
#                               f"{ma['title'][:28]} ↔ {mb['title'][:28]}")
#                         continue
#                     ya = ma.get("yes") or 0.0
#                     yb = mb.get("yes") or 0.0
#                     spread = max(yb - ya, ya - yb) if (ya > 0 and yb > 0) else 0.0
#                     fees = FEES[a] + FEES[b]
#                     pi = round(spread - fees, 4)
#                     matches.append({"a": a, "b": b, "cat": ma["cat"],
#                                     "ta": ma["title"], "tb": mb["title"],
#                                     "gross": round(spread, 4),
#                                     "fees": round(fees, 4), "pi": pi})
#                     L(f"MATCH {a}×{b} Π {pi*100:.1f}¢: "
#                       f"{ma['title'][:28]} ↔ {mb['title'][:28]}")
#             L(f"banding {a}×{b}: {n_pair} pairs")
#     near.sort(key=lambda x: -x["s"])
#     matches.sort(key=lambda m: -m["pi"])
#     L(f"selesai: {comparisons} perbandingan · {len(matches)} match · "
#       f"{round(time.time()-t0,1)} dtk")
#     info = {"counts": {v: len(rows[v]) for v in rows},
#             "comparisons": comparisons,
#             "ts": time.strftime("%H:%M:%S"),
#             "epoch": int(time.time()),
#             "duration": round(time.time() - t0, 1)}
#     return matches[:10], info, near[:5], log[-150:]


# # === Main Loop ===
# def _loop():
#     """Loop eksekusi keputusan (paper/real)."""
#     global _run, _last_reaper_ts, _last_alert_ts
#     errs = 0
#     _log_loop("loop start")
#     while _run:
#         t0 = time.time()
#         try:
#             cfg = load_config()
#             st = _read()
#             st["running"] = True
#             if (time.time() - _last_scan_ts >= SCAN_EVERY_SEC) or not st.get("matches"):
#                 st["matches"], st["info"], st["near"], st["scanlog"] = _scan_shared()
#                 st["interval"] = INTERVAL

#             # Reaper: auto-cancel order Limitless GTC yang nyangkut
#             if time.time() - _last_reaper_ts >= REAPER_EVERY_SEC:
#                 _last_reaper_ts = time.time()
#                 from app.executor import reap_limitless_stale
#                 try:
#                     count, tickers, err = reap_limitless_stale()
#                 except Exception as reaper_exc:
#                     _log_loop(f"reaper exception: {type(reaper_exc).__name__}: {reaper_exc}")
#                     count, tickers, err = 0, [], None
#                 if count > 0:
#                     _log_loop(f"reaper: cancelled {count} stale orders: {tickers}")
#                 elif err:
#                     _log_loop(f"reaper: {err}")
#                 else:
#                     _log_loop("reaper: skip (no open orders)")
            
#             # Alert check: pantau kondisi kritis tiap 60 detik
#             if time.time() - _last_alert_ts >= ALERT_CHECK_SEC:
#                 _last_alert_ts = time.time()
#                 # Cek auto_stop
#                 if st.get("auto_stop"):
#                     dispatch_alert("critical", f"Engine auto-stop: {st['auto_stop']}", "auto_stop")
#                 # Cek last_error tidak kosong > 5 menit
#                 if st.get("last_error"):
#                     dispatch_alert("warning", f"Loop error: {st['last_error']}", "last_error")
#                 # Cek thread mati (watchdog gagal respawn)
#                 if _run and _thr is not None and not _thr.is_alive():
#                     dispatch_alert("critical", "Loop thread mati, watchdog gagal respawn", "thread_dead")
#                     st.setdefault("trades", []).append({
#                         "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
#                         "mode": "cancel-auto",
#                         "venues": ["limitless"],
#                         "pi": 0.0,
#                         "size": 0.0,
#                         "note": f"cancelled {count} stale GTC orders: {', '.join(tickers[:3])}"
#                     })
#                     st["trades"] = st["trades"][-50:]
#                 elif err:
#                     _log_loop(f"reaper: {err}")
                                    
#             lim = cfg.get("limits", {})
#             minp = float(lim.get("min_profit", 0.5)) / 100
#             per_op = float(lim.get("modal_per_op", 2))
#             cap = float(lim.get("rugi_harian", 5))

#             today = time.strftime("%Y-%m-%d")
#             sp = st.get("spend", {})
#             if sp.get("today") != today:
#                 sp = {"today": today, "amount": 0.0}

#             added = 0
#             for m in st["matches"]:
#                 if m["pi"] < minp:
#                     continue
#                 if st.get("mode") == "real" and sp["amount"] + per_op <= cap:
#                     for venue in (m["a"], m["b"]):
#                         fn = EXEC.get(venue)
#                         if not fn:
#                             continue
#                         _usd = max(per_op, MIN_ORDER_USD.get(venue, 0.0))
#                         ok, msg = fn(load_creds().get(venue, {}), usd=_usd)
#                         if ok:
#                             sp["amount"] = round(sp["amount"] + per_op, 2)
#                             st.setdefault("trades", []).append({
#                                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
#                                 "mode": "real-auto", "venues": [venue],
#                                 "pi": m["pi"], "size": per_op, "note": msg[:60]})
#                             st["trades"] = st["trades"][-50:]
#                             added += 1
#                 else:
#                     st.setdefault("trades", []).append({
#                         "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
#                         "mode": st.get("mode", "paper"),
#                         "venues": [m["a"], m["b"]], "pi": m["pi"], "size": per_op})
#                     st["trades"] = st["trades"][-50:]
#                     added += 1

#             st["spend"] = sp
#             errs = 0
#             st.pop("last_error", None)

#             if sp["amount"] >= cap:
#                 st["auto_stop"] = (f"{time.strftime('%H:%M:%S')} "
#                                    f"cap rugi harian tercapai ${sp['amount']:.2f}")
#                 _write(st)
#                 _log_loop("auto-stop cap harian")
#                 stop()
#                 break
#             _write(st)
#             _log_loop(f"cycle ok matches={len(st.get('matches') or [])} +trades={added}")
#             time.sleep(max(5, INTERVAL - (time.time() - t0)))
#         except Exception as e:
#             errs += 1
#             _log_loop(f"cycle error {type(e).__name__}: {e}")
#             st = _read()
#             st["last_error"] = f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {e}"
#             if errs >= 5:
#                 st["auto_stop"] = (f"{time.strftime('%H:%M:%S')} "
#                                    f"5 error beruntun: {type(e).__name__}")
#                 _write(st)
#                 _log_loop("auto-stop 5 error")
#                 stop()
#                 break
#             _write(st)
#             time.sleep(5)
#     _log_loop("loop exit")


# # === Refresh untuk Dashboard ===
# def refresh():
#     """Scan baru sekarang juga (dipakai saat halaman dashboard dibuka)."""
#     if KILL.exists() or not _run:
#         return status()
#     st = _read()
#     if time.time() - _last_scan_ts >= 45:
#         st["matches"], st["info"], st["near"], st["scanlog"] = _scan_shared()
#     st["interval"] = INTERVAL
#     _write(st)
#     return st


# # === Watchdog ===
# def _watchdog():
#     """Pastikan thread loop tetap hidup."""
#     global _thr
#     while True:
#         time.sleep(20)
#         try:
#             if _run and (_thr is None or not _thr.is_alive()):
#                 _log_loop("watchdog: respawn loop")
#                 _thr = threading.Thread(target=_loop, daemon=True)
#                 _thr.start()
#         except Exception:
#             pass


# # === Kontrol Engine ===
# def start(mode):
#     """Mulai engine (paper/real)."""
#     global _thr, _run, _wd_on
#     if KILL.exists():
#         return False, "kill switch aktif — buka kunci dulu"
#     if _run:
#         return False, "sudah berjalan"
#     st = _read()
#     st["mode"] = mode
#     st.pop("auto_stop", None)
#     _write(st)
#     _start_session(mode)
#     _run = True
#     _thr = threading.Thread(target=_loop, daemon=True)
#     _thr.start()
#     if not _wd_on:
#         _wd_on = True
#         threading.Thread(target=_watchdog, daemon=True).start()
#     _log_loop(f"engine started mode={mode}")
#     return True, f"engine {mode} dimulai"


# def stop():
#     """Hentikan engine."""
#     global _run
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
#         st["trades"] = st["trades"][-50:]
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

