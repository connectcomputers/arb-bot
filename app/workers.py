"""Workers S7: paper-resolver (ea/eb faktual + fallback judul) + negrisk. Paper-only."""
import json, re, threading, time, urllib.request

_SYM = [("ethereum", "ETHUSDT"), ("bitcoin", "BTCUSDT"), ("solana", "SOLUSDT"),
        ("dogecoin", "DOGEUSDT"), ("hyperliquid", "HYPEUSDT"), ("zcash", "ZECUSDT"),
        ("litecoin", "LTCUSDT"), ("binance", "BNBUSDT"), ("ripple", "XRPUSDT"),
        ("eth", "ETHUSDT"), ("btc", "BTCUSDT"), ("sol", "SOLUSDT"),
        ("doge", "DOGEUSDT"), ("hype", "HYPEUSDT"), ("zec", "ZECUSDT"),
        ("ltc", "LTCUSDT"), ("bnb", "BNUSDT".replace("BNUSDT", "BNBUSDT")), ("xrp", "XRPUSDT")]


def _sym_of(title):
    s = (title or "").lower()
    for kw, sym in _SYM:
        if re.search(r"\b" + kw + r"\b", s):
            return sym
    return None
_INT = {300: "5m", 900: "15m", 3600: "1h", 86400: "1d", 604800: "1w"}

def _range_step(title):
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*-\s*(\d{1,2}):(\d{2})\s*(AM|PM)", title or "", re.I)
    if not m:
        s = (title or "").lower()
        for kw, st in (("5 min", 300), ("15 min", 900), ("hourly", 3600), ("daily", 86400)):
            if kw in s:
                return st
        return 300
    def mins(h, mi, ap):
        h = int(h) % 12 + (0 if ap.upper() == "AM" else 12)
        return h * 60 + int(mi)
    d = mins(m.group(4), m.group(5), m.group(6)) - mins(m.group(1), m.group(2), m.group(3))
    return abs(d) * 60 or 300

def _step_of(title):
    s = (title or "").lower()
    for kw, st in (("5 min", 300), ("15 min", 900), ("hourly", 3600), ("daily", 86400), ("weekly", 604800)):
        if kw in s:
            return st
    return None

def _kline(sym, interval, start_epoch):
    url = (f"https://api.binance.com/api/v3/klines?symbol={sym}"
           f"&interval={interval}&startTime={int(start_epoch)*1000}&limit=1")
    with urllib.request.urlopen(url, timeout=10) as r:
        k = json.loads(r.read())[0]
    return float(k[1]), float(k[4])

def _yes_win(sym, end, step):
    if not sym or step not in _INT:
        return None
    o, c = _kline(sym, _INT[step], end - step)
    return 1 if c > o else 0

def _sides(d):
    if d in ("YES_NO", "CROSS_CAT"): return "YES", "NO"
    if d == "NO_YES": return "NO", "YES"
    return None, None

def resolve_once():
    from app import engine as E
    st = E._read()
    now = time.time()
    checked = done = noend = future = noasset = 0
    for t in st.get("trades", []):
        if t.get("mode") != "paper" or t.get("resolved"):
            continue
        ta, tb = t.get("ta") or "", t.get("tb") or ""
        if not ta or not tb:
            continue
        checked += 1
        ea = t.get("ea") or None
        eb = t.get("eb") or None
        if not ea or not eb:
            noend += 1
            continue
        if now < max(ea, eb) + 120:
            future += 1
            continue
        sa = _range_step(ta) if not _step_of(ta) else _step_of(ta)
        sb = _step_of(tb) or _range_step(tb)
        wa = _yes_win(_sym_of(ta), ea, sa)
        wb = _yes_win(_sym_of(tb), eb, sb)
        if wa is None or wb is None:
            noasset += 1
            continue
        da, db = _sides(t.get("direction"))
        if da is None:
            continue
        pay = (wa if da == "YES" else 1 - wa) + (wb if db == "YES" else 1 - wb)
        pnl = round(float(t.get("size", 5)) * (pay - 1 + float(t.get("pi", 0))), 2)
        t["resolved"] = True
        t["pnl"] = pnl
        t["resolved_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        t["resolver"] = "binance-proxy"
        t["outcomes"] = [wa, wb]
        done += 1
        try:
            with open("data/paper_resolved.jsonl", "a") as f:
                f.write(json.dumps(t) + "\n")
        except Exception:
            pass
    if done:
        E._write(st)
    E._log_loop(f"resolver: checked={checked} resolved={done} noend={noend} future={future} noasset={noasset}")
    return done

def negrisk_once():
    from app import engine as E
    from app.config_store import load_creds
    from app.venue_markets import _poly_events
    try:
        rs = _poly_events(load_creds()["polymarket"])
    except Exception:
        return 0
    st = E._read()
    donek = st.setdefault("negrisk_done", {})
    added = 0
    for r in rs:
        ys = [y for y in (r.get("yes_list") or []) if 0.005 < y < 0.995]
        if len(ys) < 3:
            continue
        s = sum(ys)
        key = r["title"][:60]
        if key in donek:
            continue
        side, profit = None, 0.0
        if s < 0.98: side, profit = "YES", 1.0 - s
        elif s > 1.02: side, profit = "NO", s - 1.0
        if side is None:
            continue
        donek[key] = time.strftime("%Y-%m-%dT%H:%M:%S")
        st.setdefault("trades", []).append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "paper",
            "venues": ["polymarket"], "pi": round(profit, 4), "size": 5.0,
            "direction": "NEGRISK_" + side, "ta": key,
            "tb": f"{len(ys)} outcomes S={s:.3f}", "locked": True,
            "resolved": True, "pnl": round(5.0 * profit, 2),
            "resolved_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "resolver": "negrisk-locked"})
        st["trades"] = st["trades"][-10000:]
        added += 1
        E._log_loop(f"negrisk paper: {side} S={s:.3f} {key[:40]}")
    if added:
        E._write(st)
    return added

def _loop(fn, every, tag):
    while True:
        try:
            fn()
        except Exception as e:
            try:
                from app import engine as E
                E._log_loop(f"{tag} error: {e}")
            except Exception:
                pass
        time.sleep(every)

_started = False
def start_workers():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, args=(resolve_once, 300, "resolver"), daemon=True).start()
    threading.Thread(target=_loop, args=(negrisk_once, 120, "negrisk"), daemon=True).start()
