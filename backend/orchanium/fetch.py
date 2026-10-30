"""Cached page fetching + text extraction (HTML and PDF) for citation checks
and figure discovery."""
from __future__ import annotations

import asyncio
import io
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .config import settings
from .store import get_store

CACHE_NS = "fetch.v1"
MAX_TEXT = 400_000
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/128.0 Safari/537.36 Orchanium/0.1 (research prototype)")
# Wikipedia (and others) accept bots only when the UA carries a contact URL.
_BOT_UA = ("OrchaniumBot/0.1 (" + (f"+{settings.fetch_contact_url}; " if settings.fetch_contact_url else "")
           + "research prototype; citation verification) python-httpx")
_CACHEABLE = {200, 404, 410}
_sem: asyncio.Semaphore | None = None
_inflight: dict[str, asyncio.Future] = {}


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(6)
    return _sem


def _html_to_text(html: str, base: str) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    images = []
    for img in soup.find_all("img")[:80]:
        src = img.get("src") or img.get("data-src")
        if src and not src.startswith("data:"):
            images.append({"url": urljoin(base, src), "alt": (img.get("alt") or "")[:200]})
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return text, images


def _pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages[:40]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


async def _fetch(url: str) -> dict:
    async with _semaphore():
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=25) as c:
                r = await c.get(url, headers={"User-Agent": _UA, "Accept": "*/*"})
                if r.status_code in (401, 403, 429):
                    # some sites (e.g. Wikipedia) reject browser-like UAs but accept honest bot UAs
                    r = await c.get(url, headers={"User-Agent": _BOT_UA, "Accept": "*/*"})
        except httpx.HTTPError as e:
            return {"url": url, "status": None, "error": f"{type(e).__name__}: {e}"[:300], "text": "", "images": []}
    ctype = r.headers.get("content-type", "")
    out = {"url": url, "final_url": str(r.url), "status": r.status_code, "content_type": ctype,
           "text": "", "images": [], "error": None}
    if r.status_code != 200:
        return out
    try:
        if "pdf" in ctype or str(r.url).lower().endswith(".pdf"):
            out["text"] = await asyncio.to_thread(_pdf_to_text, r.content)
        elif "html" in ctype or "xml" in ctype or "text" in ctype:
            out["text"], out["images"] = await asyncio.to_thread(_html_to_text, r.text, str(r.url))
    except Exception as e:  # noqa: BLE001
        out["error"] = f"text extraction failed: {e}"[:300]
    out["text"] = out["text"][:MAX_TEXT]
    return out


async def fetch_page(url: str) -> dict:
    store = get_store()
    if (hit := store.cache_get(CACHE_NS, url)) is not None:
        return {**hit, "cached": True}
    if url in _inflight:
        return await _inflight[url]
    fut = asyncio.get_running_loop().create_future()
    _inflight[url] = fut
    try:
        page = await _fetch(url)
        if page["status"] in _CACHEABLE:      # blocks / throttling / 5xx may be transient
            store.cache_set(CACHE_NS, url, page)
        fut.set_result(page)
        return page
    finally:
        _inflight.pop(url, None)
