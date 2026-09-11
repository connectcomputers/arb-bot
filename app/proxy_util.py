# app/proxy_util.py
"""Utilitas proxy terisolasi untuk endpoint Polymarket."""
import os
from contextlib import contextmanager


def get_poly_proxy() -> str:
    """Ambil proxy_url Polymarket dari credentials; '' bila tidak ada."""
    try:
        from app.config_store import load_creds
        return str((load_creds().get("polymarket") or {}).get("proxy_url") or "").strip()
    except Exception:
        return ""


@contextmanager
def poly_proxy(proxy_url: str = None):
    """Pinjam proxy Polymarket sementara; env dikembalikan setelah blok."""
    keys = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")
    old = {k: os.environ.get(k) for k in keys}
    p = str(proxy_url if proxy_url is not None else get_poly_proxy()).strip()
    if p:
        os.environ["HTTPS_PROXY"] = p
        os.environ["HTTP_PROXY"] = p
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v