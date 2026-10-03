"""Workers S5: paper-resolver (wasit proxy Binance) + negrisk Polymarket.
Paper-only. Tidak pernah menyentuh order real. Thread-safe via engine._read/_write."""
import json, threading, time, urllib.request

_BIN = {"bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT",
        "dogecoin": "DOGEUSDT", "bnb": "BNBUSDT", "xrp": "XRPUSDT",
        "litecoin": "LTCUSDT"}
_INT = {300: "5m", 900: "15m", 3600: "1h", 86400: "1d", 604800: "1w"}


def _kline(symbol, interval, start_epoch):
    url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
           f"&interval={interval}&startTime={int(start_epoch)*1000}&limit=1")
    with urllib.request.urlopen(url, timeout=10) as r:
        k = json.loads(r.read())[0]
    return float(k[1]), float(k[4])


def _yes_win(asset, start, end):
    sym = _BIN.get(asset)
    if not sym:
        return None
    o, c = _kline(sym, _INT.get(int(end - start), "5m"), start)
    return 1 if c > o else 0


def _sides(direction):
    if direction in ("YES_NO", "CROSS_CAT"):
        return "YES", "NO"
    if direction == "NO_YES":
        return "NO", "YES"
    return None, None


def resolve_once():
    from app import engine as E
    st = E._read()
    now = time.time()
    changed = 0
    for t in st.get("trades", []):
        if t.get("mode") != "paper" or t.get("resolved"):
            continue
        ta, tb = t.get("ta") or "", t.get("tb") or ""
        if not ta or not tb:
            continue
        ea, eb = E._close_ts(ta), E._close_ts(tb)
        if not ea or not eb or now < max(ea, eb) + 120:
            continue
        wa = _yes_win(E._ckey(ta), ea - (E._wstep(ta) or 300), ea)
        wb = _yes_win(E._ckey(tb), eb - (E._wstep(tb) or 300), eb)
        if wa is None or wb is None:
            continue
        da, db = _sides(t.get("direction"))
        if da is None:
            continue
        pay = (wa if da == "YES" else 1 - wa) + (wb if db == "YES" else 1 - wb)
        fees = 0.04 if {"polymarket", "kalshi"} <= set(t.get("venues", [])) else 0.01
        cost = 1.0 - (t.get("pi", 0) + fees)
        t["resolved"] = True
        t["pnl"] = round(float(t.get("size", 5)) * (pay - cost), 2)
        t["resolved_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        t["resolver"] = "binance-proxy"
        t["outcomes"] = [wa, wb]
        changed += 1
        try:
            with open("data/paper_resolved.jsonl", "a") as f:
                f.write(json.dumps(t) + "\n")
        except Exception:
            pass
    if changed:
        E._write(st)
        E._log_loop(f"resolver: {changed} paper trades resolved")
    return changed


def negrisk_once():
    from app import engine as E
    from app.config_store import load_creds
    from app.venue_markets import _poly_events
    try:
        rs = _poly_events(load_creds()["polymarket"])
    except Exception:
        return 0
    st = E._read()
    done = st.setdefault("negrisk_done", {})
    added = 0
    for r in rs:
        ys = [y for y in (r.get("yes_list") or []) if 0.005 < y < 0.995]
        if len(ys) < 3:
            continue
        s = sum(ys)
        key = r["title"][:60]
        if key in done:
            continue
        side, profit = None, 0.0
        if s < 0.98:
            side, profit = "YES", 1.0 - s
        elif s > 1.02:
            side, profit = "NO", s - 1.0
        if side is None:
            continue
        done[key] = time.strftime("%Y-%m-%dT%H:%M:%S")
        st.setdefault("trades", []).append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": "paper", "venues": ["polymarket"],
            "pi": round(profit, 4), "size": 5.0,
            "direction": "NEGRISK_" + side,
            "ta": key, "tb": f"{len(ys)} outcomes S={s:.3f}",
            "locked": True, "resolved": True,
            "pnl": round(5.0 * profit, 2),
            "resolved_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "resolver": "negrisk-locked"})
        st["trades"] = st["trades"][-10000:]
        added += 1
        E._log_loop(f"negrisk paper: {side} S={s:.3f} {key[:40]}")
    if added:
        E._write(st)
    return added


def _loop_resolve():
    while True:
        try:
            resolve_once()
        except Exception as e:
            try:
                from app import engine as E
                E._log_loop(f"resolver error: {e}")
            except Exception:
                pass
        time.sleep(300)


def _loop_negrisk():
    while True:
        try:
            negrisk_once()
        except Exception as e:
            try:
                from app import engine as E
                E._log_loop(f"negrisk error: {e}")
            except Exception:
                pass
        time.sleep(120)


_started = False


def start_workers():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop_resolve, daemon=True).start()
    threading.Thread(target=_loop_negrisk, daemon=True).start()
