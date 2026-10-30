"""Thin async wrapper over the Meta Model API Responses endpoint.

Shapes verified by scripts/smoke_meta.py (Oct 30):
- structured output via `text.format` json_schema (strict)
- built-in `web_search` tool; `include: ["web_search_call.results"]` gives the
  sources; `web_search_call.action.query` gives the query actually run
- tool-using responses hold several `message` items; the answer is the last one
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

from ..config import settings
from ..store import get_store, hash_key

CACHE_NS = "llm.v1"


class BudgetExceeded(RuntimeError):
    pass


class MetaAPIError(RuntimeError):
    pass


# ------------------------------------------------------------------ cost / caps

class CostTracker(BaseModel):
    llm_calls: int = 0
    cached_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    searches: int = 0
    sam_images: int = 0
    usd: float = 0.0

    def snapshot(self) -> dict:
        return self.model_dump()


class Budget:
    """Per-run guardrails. `on_change` is called with the tracker after every
    billed call so the UI cost meter stays live."""

    def __init__(self, on_change: Callable[[CostTracker], None] | None = None):
        self.cost = CostTracker()
        self.on_change = on_change

    def check(self, kind: str = "llm") -> None:
        c = self.cost
        if kind == "llm" and c.llm_calls >= settings.max_llm_calls:
            raise BudgetExceeded(f"LLM call cap reached ({settings.max_llm_calls})")
        if kind == "llm" and c.tokens_in + c.tokens_out >= settings.max_tokens:
            raise BudgetExceeded(f"token cap reached ({settings.max_tokens})")
        if kind == "search" and c.searches >= settings.max_searches:
            raise BudgetExceeded(f"web search cap reached ({settings.max_searches})")
        if kind == "sam" and c.sam_images >= settings.max_sam_images:
            raise BudgetExceeded(f"SAM image cap reached ({settings.max_sam_images})")

    def add_llm(self, model: str, usage: dict, searches: int) -> float:
        p_in, p_cached, p_out = settings.price.get(model, settings.price["muse-spark-1.3"])
        tin = usage.get("input_tokens", 0)
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        tout = usage.get("output_tokens", 0)
        usd = ((tin - cached) * p_in + cached * p_cached + tout * p_out) / 1e6 + searches * settings.price_per_search
        c = self.cost
        c.llm_calls += 1
        c.tokens_in += tin
        c.tokens_out += tout
        c.searches += searches
        c.usd = round(c.usd + usd, 5)
        self._changed()
        return usd

    def add_sam(self, images: int = 1) -> float:
        usd = images * settings.price_per_sam_image
        self.cost.sam_images += images
        self.cost.usd = round(self.cost.usd + usd, 5)
        self._changed()
        return usd

    def add_cached(self) -> None:
        self.cost.cached_calls += 1
        self._changed()

    def _changed(self):
        if self.on_change:
            self.on_change(self.cost)


# ------------------------------------------------------------------ schema

def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema -> Meta strict subset: refs inlined, every object
    closed (`additionalProperties: false`) with all keys required, no defaults."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            # strip schema annotations, but never entries of a `properties` map
            # (a field may legitimately be called "title" or "default")
            node = {k: ({pk: walk(pv) for pk, pv in v.items()} if k == "properties" else walk(v))
                    for k, v in node.items() if k not in ("default", "title")}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)


# ------------------------------------------------------------------ response

class SearchCall(BaseModel):
    query: str | None
    results: list[dict] = Field(default_factory=list)   # {title, url, snippet}


class MetaResponse(BaseModel):
    id: str | None = None
    model: str
    text: str
    parsed: Any = None
    annotations: list[dict] = Field(default_factory=list)
    searches: list[SearchCall] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False


def normalize_url(url: str | None) -> str | None:
    """Lower-case scheme and host (the API sometimes returns 'Www.Mdpi.Com');
    path and query are case-sensitive and left untouched."""
    if not url:
        return url
    try:
        p = urlsplit(url)
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, p.fragment))
    except ValueError:
        return url


def _parse_output(data: dict) -> tuple[str, list[dict], list[SearchCall]]:
    messages: list[tuple[str, list[dict]]] = []
    searches: list[SearchCall] = []
    for item in data.get("output", []):
        t = item.get("type")
        if t == "message":
            text, anns = "", []
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text += c.get("text", "")
                    for a in c.get("annotations") or []:
                        anns.append({**a, "url": normalize_url(a.get("url"))})
            messages.append((text, anns))
        elif t == "web_search_call":
            action = item.get("action") or {}
            searches.append(SearchCall(
                query=action.get("query"),
                results=[{**r, "url": normalize_url(r.get("url"))} for r in item.get("results") or []],
            ))
    text = messages[-1][0] if messages else ""
    annotations = [a for _, anns in messages for a in anns]
    return text, annotations, searches


# ------------------------------------------------------------------ client

class MetaClient:
    def __init__(self, budget: Budget | None = None):
        if not settings.meta_api_key:
            raise MetaAPIError("META_API_KEY / MODEL_API_KEY not configured")
        self.budget = budget or Budget()
        self._http = httpx.AsyncClient(
            base_url=settings.meta_base_url,
            headers={"Authorization": f"Bearer {settings.meta_api_key}"},
            timeout=httpx.Timeout(settings.agent_timeout_s, connect=20),
        )

    async def aclose(self):
        await self._http.aclose()

    async def _post(self, body: dict, attempts: int = 3) -> dict:
        last = None
        for i in range(attempts):
            try:
                r = await self._http.post("/responses", json=body)
            except httpx.TransportError as e:
                last = str(e)
            else:
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}: {r.text[:500]}"
                if r.status_code not in (408, 409, 429, 500, 502, 503, 504):
                    raise MetaAPIError(last)
            await asyncio.sleep(2.0 * 2 ** i)
        raise MetaAPIError(f"Meta API failed after {attempts} attempts: {last}")

    async def respond(
        self,
        input: str | list,
        *,
        instructions: str | None = None,
        schema: type[BaseModel] | None = None,
        web_search: bool = False,
        search_context: str = "medium",
        effort: str = "low",
        model: str | None = None,
        max_output_tokens: int | None = None,
        use_cache: bool = True,
    ) -> MetaResponse:
        model = model or settings.meta_model
        body: dict[str, Any] = {"model": model, "input": input, "reasoning": {"effort": effort}}
        if instructions:
            body["instructions"] = instructions
        if schema is not None:
            body["text"] = {"format": {"type": "json_schema", "name": schema.__name__,
                                       "schema": strict_schema(schema), "strict": True}}
        if web_search:
            body["tools"] = [{"type": "web_search", "search_context_size": search_context}]
            body["include"] = ["web_search_call.results"]
        if max_output_tokens:
            body["max_output_tokens"] = max_output_tokens

        key = hash_key(body)
        store = get_store()
        if use_cache and (hit := store.cache_get(CACHE_NS, key)):
            self.budget.add_cached()
            resp = MetaResponse(**{**hit, "cached": True, "usd": 0.0})
            return self._attach_parsed(resp, schema)

        self.budget.check("llm")
        if web_search:
            self.budget.check("search")
        t0 = time.time()
        data = await self._post(body)
        text, anns, searches = _parse_output(data)
        usage = data.get("usage") or {}
        usd = self.budget.add_llm(model, usage, len(searches))
        resp = MetaResponse(id=data.get("id"), model=model, text=text, annotations=anns, searches=searches,
                            usage=usage, usd=round(usd, 5), latency_s=round(time.time() - t0, 2))
        if data.get("status") == "completed" or text:
            store.cache_set(CACHE_NS, key, resp.model_dump(exclude={"parsed", "cached"}))
        return self._attach_parsed(resp, schema)

    @staticmethod
    def _attach_parsed(resp: MetaResponse, schema: type[BaseModel] | None) -> MetaResponse:
        if schema is not None:
            try:
                resp.parsed = schema.model_validate(json.loads(resp.text))
            except Exception as e:  # noqa: BLE001
                raise MetaAPIError(f"structured output did not validate: {e}; text={resp.text[:300]!r}") from e
        return resp

    # -------- raw call used by SAM (different output grammar, image billing)
    async def raw(self, body: dict) -> dict:
        return await self._post(body)
