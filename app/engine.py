"""Engine S3: match lintas venue + Π, eksekusi PAPER. REAL = S4."""
import json
import re
import threading
import time
from pathlib import Path

from app.config_store import load_config, load_creds
from app.venue_markets import FETCH

STATE = Path("data") / "live_state.json"
KILL = Path("data") / "kill.json"
FEES = {"polymarket": 0.0, "kalshi": 0.04, "limitless": 0.004}

_thr = None
_run = False

STOP = set("on in by at will the of for a an or and to with from be is above "
           "below up down hit close end before after".split())


def _tok(t):
    return set(w for w in re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split()
               if w not in STOP)


def sim(a, b):
    ta, tb = _tok(a), _tok(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _read():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"running": False, "mode": "paper", "matches": [], "trades": []}


def _write(st):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def _scan():
    cfg = load_config()
    creds = load_creds()
    pairs = cfg.get("pairs", {})
    venues = [v for v, s in cfg["venues"].items()
              if s.get("valid") and s.get("enabled") and pairs.get(v)]
    rows = {}
    for v in venues:
        try:
            allr = FETCH[v](creds.get(v, {}))
        except Exception:
            allr = []
        rows[v] = [r for r in allr
                   if r["cat"] in pairs[v] and r.get("yes")]
    matches = []
    vs = list(rows)
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            a, b = vs[i], vs[j]
            for ma in rows[a][:40]:
                for mb in rows[b][:40]:
                    if ma["cat"] != mb["cat"] or sim(ma["title"], mb["title"]) < 0.6:
                        continue
                    pi = max(mb["yes"] - ma["yes"], ma["yes"] - mb["yes"]) \
                         - FEES[a] - FEES[b]
                    if pi > 0:
                        matches.append({"a": a, "b": b, "cat": ma["cat"],
                                        "ta": ma["title"], "tb": mb["title"],
                                        "pi": round(pi, 4)})
    matches.sort(key=lambda m: -m["pi"])
    return matches[:10]


def _loop():
    global _run
    while _run:
        cfg = load_config()
        st = _read()
        st["running"] = True
        st["matches"] = _scan()
        lim = cfg.get("limits", {})
        minp = float(lim.get("min_profit", 0.5)) / 100
        for m in st["matches"]:
            if m["pi"] >= minp:
                st.setdefault("trades", []).append({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "mode": st.get("mode", "paper"),
                    "venues": [m["a"], m["b"]], "pi": m["pi"],
                    "size": float(lim.get("modal_per_op", 1))})
        st["trades"] = st["trades"][-50:]
        _write(st)
        time.sleep(60)


def start(mode):
    global _thr, _run
    if KILL.exists():
        return False, "kill switch aktif — buka kunci dulu"
    if _run:
        return False, "sudah berjalan"
    st = _read()
    st["mode"] = mode
    _write(st)
    _run = True
    _thr = threading.Thread(target=_loop, daemon=True)
    _thr.start()
    return True, f"engine {mode} dimulai"


def stop():
    global _run
    _run = False
    st = _read()
    st["running"] = False
    _write(st)


def kill():
    stop()
    KILL.parent.mkdir(exist_ok=True)
    KILL.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}))


def unkill():
    if KILL.exists():
        KILL.unlink()


def status():
    st = _read()
    st["running"] = bool(_run)
    st["kill"] = KILL.exists()
    return st