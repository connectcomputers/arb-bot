"""Engine S3: match lintas venue + Π, eksekusi PAPER. REAL = S4."""
import json
import re
import threading
import time
from pathlib import Path

from app.config_store import load_config, load_creds
from app.venue_markets import FETCH
from app.venue_markets import FETCH, _poly_events, _kalshi_events
from app.executor import EXEC

SESSION = Path("data") / "session.json"

STATE = Path("data") / "live_state.json"
KILL = Path("data") / "kill.json"
FEES = {"polymarket": 0.0, "kalshi": 0.04, "limitless": 0.004}

INTERVAL = 30

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

#     t0 = time.time()
#     comparisons = 0
#     matches = []
#     near = []
#     vs = list(rows)
#     for i in range(len(vs)):
#         for j in range(i + 1, len(vs)):
#             a, b = vs[i], vs[j]
#             for ma in rows[a][:60]:
#                 ka = crypto_key(ma["title"]) if ma["cat"] == "crypto" else None
#                 for mb in rows[b][:60]:
#                     if ma["cat"] != mb["cat"]:
#                         continue
#                     comparisons += 1
#                     kb = crypto_key(mb["title"]) if mb["cat"] == "crypto" else None
#                     s = sim(ma["title"], mb["title"])
#                     same = (ka and ka == kb) or s >= 0.5
#                     if not same:
#                         if s >= 0.25:
#                             near.append({"a": a, "b": b, "s": round(s, 2),
#                                          "ta": ma["title"][:40],
#                                          "tb": mb["title"][:40]})
#                         continue
#                     ya = ma.get("yes") or 0.0
#                     yb = mb.get("yes") or 0.0
#                     spread = max(yb - ya, ya - yb) if (ya > 0 and yb > 0) else 0.0
#                     fees = FEES[a] + FEES[b]
#                     matches.append({"a": a, "b": b, "cat": ma["cat"],
#                                     "ta": ma["title"], "tb": mb["title"],
#                                     "gross": round(spread, 4),
#                                     "fees": round(fees, 4),
#                                     "pi": round(spread - fees, 4)})
#     near.sort(key=lambda x: -x["s"])
#     matches.sort(key=lambda m: -m["pi"])        # laba terbesar → terkecil
#     info = {"counts": {v: len(rows[v]) for v in rows},
#             "comparisons": comparisons,
#             "ts": time.strftime("%H:%M:%S"),
#             "epoch": int(time.time()), # <- Tambah ini
#             "duration": round(time.time() - t0, 1)}
#     return matches[:10], info, near[:5]

def _scan():
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
                    same = (ka and ka == kb) or s >= 0.5
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
                    spread = max(yb - ya, ya - yb) if (ya > 0 and yb > 0) else 0.0
                    fees = FEES[a] + FEES[b]
                    pi = round(spread - fees, 4)
                    matches.append({"a": a, "b": b, "cat": ma["cat"],
                                    "ta": ma["title"], "tb": mb["title"],
                                    "gross": round(spread, 4),
                                    "fees": round(fees, 4), "pi": pi})
                    L(f"MATCH {a}×{b} Π {pi*100:.1f}¢: "
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
    return matches[:10], info, near[:5], log[-40:]

# def _loop():
#     global _run
#     while _run:
#         try:
#             cfg = load_config()
#             st = _read()
#             st["running"] = True
#             st["matches"], st["info"], st["near"], st["scanlog"] = _scan()
#             lim = cfg.get("limits", {})
#             minp = float(lim.get("min_profit", 0.5)) / 100
#             per_op = float(lim.get("modal_per_op", 2))
            
#             # cap belanja harian
#             today = time.strftime("%Y-%m-%d")
#             sp = st.get("spend", {})
#             if sp.get("today") != today:
#                 sp = {"today": today, "amount": 0.0}
#             cap = float(lim.get("rugi_harian", 5))
            
#             for m in st["matches"]:
#                 if m["pi"] >= minp:
#                     # auto-exec bila mode = real & cap belum tercapai
#                     if st.get("mode") == "real" and sp["amount"] + per_op <= cap:
#                         from app.executor import EXEC
#                         for venue in [m["a"], m["b"]]:
#                             fn = EXEC.get(venue)
#                             if fn:
#                                 ok, msg = fn(load_creds().get(venue, {}), usd=per_op)
#                                 if ok:
#                                     sp["amount"] = round(sp["amount"] + per_op, 2)
#                                     st.setdefault("trades", []).append({
#                                         "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
#                                         "mode": "real-auto",
#                                         "venues": [venue], "pi": m["pi"],
#                                         "size": per_op, "note": msg[:60]})
#                                     st["trades"] = st["trades"][-50:]
#                     else:
#                         # paper mode atau cap tercapai
#                         st.setdefault("trades", []).append({
#                             "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
#                             "mode": st.get("mode", "paper"),
#                             "venues": [m["a"], m["b"]], "pi": m["pi"],
#                             "size": per_op})
#                         st["trades"] = st["trades"][-50:]
            
#             st["spend"] = sp
#             st["interval"] = INTERVAL
#             st.pop("last_error", None)
#             _write(st)
#             time.sleep(INTERVAL)
#         except Exception as e:
#             st = _read()
#             st["last_error"] = f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {e}"
#             _write(st)
#             time.sleep(5)

def _loop():
    global _run
    errs = 0
    while _run:
        try:
            cfg = load_config()
            st = _read()
            st["running"] = True
            st["matches"], st["info"], st["near"], st["scanlog"] = _scan()
            lim = cfg.get("limits", {})
            minp = float(lim.get("min_profit", 0.5)) / 100
            per_op = float(lim.get("modal_per_op", 2))
            cap = float(lim.get("rugi_harian", 5))

            today = time.strftime("%Y-%m-%d")
            sp = st.get("spend", {})
            if sp.get("today") != today:
                sp = {"today": today, "amount": 0.0}

            for m in st["matches"]:
                if m["pi"] < minp:
                    continue
                if st.get("mode") == "real" and sp["amount"] + per_op <= cap:
                    from app.executor import EXEC
                    for venue in (m["a"], m["b"]):
                        fn = EXEC.get(venue)
                        if not fn:
                            continue
                        ok, msg = fn(load_creds().get(venue, {}), usd=per_op)
                        if ok:
                            sp["amount"] = round(sp["amount"] + per_op, 2)
                            st.setdefault("trades", []).append({
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "mode": "real-auto", "venues": [venue],
                                "pi": m["pi"], "size": per_op, "note": msg[:60]})
                            st["trades"] = st["trades"][-50:]
                else:
                    st.setdefault("trades", []).append({
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "mode": st.get("mode", "paper"),
                        "venues": [m["a"], m["b"]], "pi": m["pi"], "size": per_op})
                    st["trades"] = st["trades"][-50:]

            st["spend"] = sp
            st["interval"] = INTERVAL
            errs = 0
            st.pop("last_error", None)

            # ---- AUTO-STOP 1: cap rugi harian ----
            if sp["amount"] >= cap:
                st["auto_stop"] = (f"{time.strftime('%H:%M:%S')} "
                                   f"cap rugi harian tercapai ${sp['amount']:.2f}")
                _write(st)
                stop()
                break
            _write(st)
            time.sleep(INTERVAL)
        except Exception as e:
            errs += 1
            st = _read()
            st["last_error"] = f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {e}"
            # ---- AUTO-STOP 2: 5 error beruntun ----
            if errs >= 5:
                st["auto_stop"] = (f"{time.strftime('%H:%M:%S')} "
                                   f"5 error beruntun: {type(e).__name__}")
                _write(st)
                stop()
                break
            _write(st)
            time.sleep(5)
                        
# def refresh():
#     """Scan baru sekarang juga (dipakai saat halaman dashboard dibuka)."""
#     st = _read()
#     st["matches"], st["info"], st["near"], st["scanlog"] = _scan()
#     st["interval"] = INTERVAL
#     _write(st)
#     return st

def refresh():
    if KILL.exists() or not _run:     # ← kunci: tidak scan saat berhenti/kill
        return status()
    st = _read()
    st["matches"], st["info"], st["near"], st["scanlog"] = _scan()
    st["interval"] = INTERVAL
    _write(st)
    return st

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


# def stop():
#     global _run
#     _run = False
#     st = _read()
#     st["running"] = False
#     _write(st)

def stop():
    global _run
    was_real = _session_mode() == "real"
    if SESSION.exists():
        SESSION.unlink()
    _run = False
    st = _read()
    st["running"] = False
    if was_real:                      # real = sesi berakhir, wajib re-arm
        st["need_rearm"] = True
    _write(st)

# def kill():
#     stop()
#     KILL.parent.mkdir(exist_ok=True)
#     KILL.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}))

def kill():
    stop()
    st = _read()
    st["need_rearm"] = True           # kill = selalu akhiri sesi
    _write(st)
    KILL.parent.mkdir(exist_ok=True)
    KILL.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}))

# def unkill():
#     if KILL.exists():
#         KILL.unlink()

def unkill():
    if KILL.exists():
        KILL.unlink()
    st = _read()
    st.pop("need_rearm", None)
    st.pop("auto_stop", None)
    _write(st)

def micro_exec(venue, dry=False):
    if KILL.exists():
        return {"ok": False, "message": "kill switch aktif — eksekusi ditolak"}
    cfg = load_config()
    lim = cfg.get("limits", {})
    per_op = float(lim.get("modal_per_op", 2))
    st = _read()

    # cap belanja harian (proxy rugi harian untuk demo)
    today = time.strftime("%Y-%m-%d")
    sp = st.get("spend", {})
    if sp.get("today") != today:
        sp = {"today": today, "amount": 0.0}
    cap = float(lim.get("rugi_harian", 5))
    if not dry and sp["amount"] + per_op > cap:
        return {"ok": False,
                "message": f"cap harian tercapai (${sp['amount']:.2f}/${cap:.2f})"}

    fn = EXEC.get(venue)
    if not fn:
        return {"ok": False, "message": "venue tidak dikenal"}
    ok, msg = fn(load_creds().get(venue, {}), usd=per_op, dry=dry)

    if ok and not dry:
        sp["amount"] = round(sp["amount"] + per_op, 2)
        st["spend"] = sp
        st.setdefault("trades", []).append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "real-micro",
            "venues": [venue], "pi": 0.0, "size": per_op, "note": msg[:60]})
        st["trades"] = st["trades"][-50:]
        _write(st)
    return {"ok": ok, "message": msg}

# def status():
#     st = _read()
#     st["running"] = bool(_run)
#     st["kill"] = KILL.exists()
#     return st

def status():
    st = _read()
    st["running"] = bool(_run)
    st["kill"] = KILL.exists()
    st["session"] = _session_mode()
    return st