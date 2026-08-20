"""Engine S3: match lintas venue + Π, eksekusi PAPER. REAL = S4."""
import json
import re
import threading
import time
from pathlib import Path

from app.config_store import load_config, load_creds
from app.venue_markets import FETCH
from app.venue_markets import FETCH, _poly_events, _kalshi_events

STATE = Path("data") / "live_state.json"
KILL = Path("data") / "kill.json"
FEES = {"polymarket": 0.0, "kalshi": 0.04, "limitless": 0.004}

_thr = None
_run = False

STOP = set("on in by at will the of for a an or and to with from be is above "
           "below up down hit close end before after".split())


# def _tok(t):
#     return set(w for w in re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).split()
#                if w not in STOP)

SYN = {"bitcoin": "btc", "ethereum": "eth", "solana": "sol",
       "dogecoin": "doge", "bnb": "bnb", "xrp": "xrp"}

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
          "august": 8, "september": 9, "october": 10}


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


# def _scan():
#     cfg = load_config()
#     creds = load_creds()
#     pairs = cfg.get("pairs", {})
#     venues = [v for v, s in cfg["venues"].items()
#               if s.get("valid") and s.get("enabled") and pairs.get(v)]

#     # ---- bangun rows: utamakan events (judul bersih), fallback markets ----
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
#             rows[v] = [r for r in allr
#                        if r["cat"] in pairs[v] and r.get("yes")]

#     # ---- matching lintas venue ----
#     matches = []
#     vs = list(rows)
#     for i in range(len(vs)):
#         for j in range(i + 1, len(vs)):
#             a, b = vs[i], vs[j]
#             for ma in rows[a][:60]:
#                 ka = crypto_key(ma["title"]) if ma["cat"] == "crypto" else None
#                 for mb in rows[b][:60]:
#                     if ma["cat"] != mb["cat"]:
#                         continue
#                     kb = crypto_key(mb["title"]) if mb["cat"] == "crypto" else None
#                     same = (ka and ka == kb) or sim(ma["title"], mb["title"]) >= 0.5
#                     if not same:
#                         continue
#                     ya = ma.get("yes") or 0.0
#                     yb = mb.get("yes") or 0.0
#                     if ya > 0 and yb > 0:
#                         spread = max(yb - ya, ya - yb)   # harga riil kedua sisi
#                     else:
#                         spread = 0.0                     # tampil saja, jangan trade
#                     pi = spread - FEES[a] - FEES[b]
#                     matches.append({"a": a, "b": b, "cat": ma["cat"],
#                                     "ta": ma["title"], "tb": mb["title"],
#                                     "pi": round(pi, 4)})
#     matches.sort(key=lambda m: -m["pi"])
#     return matches[:10]      # kandidat tampil walau Π negatif;
#                              # eksekusi tetap hanya bila Π >= min_profit

def _scan():
    cfg = load_config()
    creds = load_creds()
    pairs = cfg.get("pairs", {})
    venues = [v for v, s in cfg["venues"].items()
              if s.get("valid") and s.get("enabled") and pairs.get(v)]

    # ---- bangun rows: utamakan events (judul bersih), fallback markets ----
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
            # rows[v] = [r for r in allr
            #            if r["cat"] in pairs[v] and r.get("yes")]
            rows[v] = [r for r in allr if r["cat"] in pairs[v]]
            
    # ---- matching lintas venue + statistik + near-miss ----
    matches = []
    near = []
    vs = list(rows)
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            a, b = vs[i], vs[j]
            for ma in rows[a][:60]:
                ka = crypto_key(ma["title"]) if ma["cat"] == "crypto" else None
                for mb in rows[b][:60]:
                    if ma["cat"] != mb["cat"]:
                        continue
                    kb = crypto_key(mb["title"]) if mb["cat"] == "crypto" else None
                    s = sim(ma["title"], mb["title"])
                    same = (ka and ka == kb) or s >= 0.5
                    if not same:
                        if s >= 0.25:                     # kandidat terdekat
                            near.append({"a": a, "b": b, "s": round(s, 2),
                                         "ta": ma["title"][:40],
                                         "tb": mb["title"][:40]})
                        continue
                    ya = ma.get("yes") or 0.0
                    yb = mb.get("yes") or 0.0
                    if ya > 0 and yb > 0:
                        spread = max(yb - ya, ya - yb)    # harga riil kedua sisi
                    else:
                        spread = 0.0                      # tampil saja, jangan trade
                    pi = spread - FEES[a] - FEES[b]
                    matches.append({"a": a, "b": b, "cat": ma["cat"],
                                    "ta": ma["title"], "tb": mb["title"],
                                    "pi": round(pi, 4)})
    near.sort(key=lambda x: -x["s"])
    stats = {v: len(rows[v]) for v in rows}
    matches.sort(key=lambda m: -m["pi"])
    return matches[:10], stats, near[:5]

# def _loop():
#     global _run
#     while _run:
#         cfg = load_config()
#         st = _read()
#         st["running"] = True
#         st["matches"] = _scan()
#         lim = cfg.get("limits", {})
#         minp = float(lim.get("min_profit", 0.5)) / 100
#         for m in st["matches"]:
#             if m["pi"] >= minp:
#                 st.setdefault("trades", []).append({
#                     "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
#                     "mode": st.get("mode", "paper"),
#                     "venues": [m["a"], m["b"]], "pi": m["pi"],
#                     "size": float(lim.get("modal_per_op", 1))})
#         st["trades"] = st["trades"][-50:]
#         _write(st)
#         time.sleep(60)

def _loop():
    global _run
    while _run:
        cfg = load_config()
        st = _read()
        st["running"] = True
        st["matches"], st["stats"], st["near"] = _scan()
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