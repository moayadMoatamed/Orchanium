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
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

from ..config import settings
from ..events import MetaCall, current_agent
from ..store import get_store, hash_key
from ..termlog import blue, dim, green

CACHE_NS = "llm.v1"

# One line per Meta API request, so a terminal beside the app shows which model
# is being called and what it cost. Never carries prompt text.
#
# It owns its handler and does not propagate: uvicorn reconfigures logging when
# it boots, and a logger that relies on the root handler goes silent depending
# on import order. This log is demo evidence, so it has to be certain.
log = logging.getLogger("orchanium.meta")
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)
log.setLevel(logging.INFO)
log.propagate = False


def _k(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def price_of(model: str, usage: dict, searches: int = 0) -> float:
    """USD for one call. Pure: used both for budget accounting and telemetry,
    so the number shown on screen is the number that was charged."""
    p_in, p_cached, p_out = settings.price.get(model, settings.price["muse-spark-1.3"])
    tin = usage.get("input_tokens", 0)
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    tout = usage.get("output_tokens", 0)
    return ((tin - cached) * p_in + cached * p_cached + tout * p_out) / 1e6 + searches * settings.price_per_search


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
    """Per-run guardrails. `reserve` is the share of every cap that the current
    phase must leave untouched for later phases (the orchestrator lowers it as
    the run progresses, so research can never starve the debate or the report).
    `on_change` is called after every billed call so the UI cost meter stays live."""

    def __init__(self, on_change: Callable[[CostTracker], None] | None = None):
        self.cost = CostTracker()
        self.on_change = on_change
        self.reserve = 0.0

    def check(self, kind: str = "llm") -> None:
        c, room = self.cost, 1.0 - self.reserve
        limits = {
            "llm": [(c.llm_calls, settings.max_llm_calls, "LLM calls"),
                    (c.tokens_in + c.tokens_out, settings.max_tokens, "tokens"), (c.usd, settings.max_usd, "USD")],
            "search": [(c.searches, settings.max_searches, "web searches"), (c.usd, settings.max_usd, "USD")],
            "sam": [(c.sam_images, settings.max_sam_images, "SAM images"), (c.usd, settings.max_usd, "USD")],
        }[kind]
        for used, cap, what in limits:
            if used >= cap * room:
                phase = f" (this phase may use {room:.0%} of it)" if self.reserve else ""
                raise BudgetExceeded(f"{what} budget reached: {used:g} of {cap:g}{phase}")

    def add_llm(self, model: str, usage: dict, searches: int) -> float:
        tin = usage.get("input_tokens", 0)
        tout = usage.get("output_tokens", 0)
        usd = price_of(model, usage, searches)
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

class Tool(BaseModel):
    """A function the model may call: pydantic params in, JSON-able result out."""
    model_config = {"arbitrary_types_allowed": True}
    name: str
    description: str
    params: type[BaseModel]
    fn: Callable[[Any], Awaitable[Any]]


class MetaClient:
    def __init__(self, budget: Budget | None = None):
        if not settings.meta_api_key:
            raise MetaAPIError("META_API_KEY / MODEL_API_KEY not configured")
        self.budget = budget or Budget()
        # blind mode sets this; every request is scrubbed on the way out, so no
        # agent, prompt or tool result can carry a hidden name to the model
        self.redact: Callable[[str], str] | None = None
        # telemetry only: the run publishes these as `meta.call` events so the
        # UI can show live model calls. Never allowed to affect a run's result.
        self.on_meta_call: Callable[[MetaCall], None] | None = None
        self._http = httpx.AsyncClient(
            base_url=settings.meta_base_url,
            headers={"Authorization": f"Bearer {settings.meta_api_key}"},
            timeout=httpx.Timeout(settings.agent_timeout_s, connect=20),
        )

    async def aclose(self):
        await self._http.aclose()

    def scrub(self, obj: Any) -> Any:
        """Apply `redact` to every string in a request body."""
        if self.redact is None:
            return obj
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, list):
            return [self.scrub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.scrub(v) for k, v in obj.items()}
        return obj

    def _emit(self, call: MetaCall) -> None:
        """Report one model call. Telemetry must never break a run, so every
        failure here is swallowed."""
        try:
            who = (call.agent_id or "-").ljust(13)
            if call.cached:
                log.info("%s %s %s %s", dim("meta ←"), blue(call.model), who, dim("cached"))
            else:
                # kept under ~70 columns: the terminal shares the screen with
                # the app during a demo, and a wrapped line loses its columns
                log.info(
                    "%s %s %s %s %s %s",
                    dim("meta ←"), blue(call.model), who,
                    f"{call.latency_s:5.1f}s",
                    f"{_k(call.tokens_in):>6}→{_k(call.tokens_out):<6}",
                    (f"{call.searches} web " if call.searches else "      ") + green(f"${call.usd:.3f}"),
                )
            if self.on_meta_call:
                self.on_meta_call(call)
        except Exception:  # noqa: BLE001
            pass

    async def _post(self, body: dict, attempts: int = 3) -> dict:
        body = self.scrub(body)
        model = str(body.get("model") or settings.meta_model)
        web_search = any(t.get("type") == "web_search" for t in (body.get("tools") or []))
        agent = current_agent.get()
        log.info("%s %s %s %s", dim("meta →"), blue(model), (agent or "-").ljust(13),
                 dim("search on" if web_search else "search off"))
        last, t0 = None, time.time()
        for i in range(attempts):
            try:
                r = await self._http.post("/responses", json=body)
            except httpx.TransportError as e:
                last = str(e)
            else:
                if r.status_code == 200:
                    data = r.json()
                    usage = data.get("usage") or {}
                    searches = sum(1 for o in (data.get("output") or [])
                                   if o.get("type") == "web_search_call")
                    self._emit(MetaCall(
                        agent_id=agent, model=model, response_id=data.get("id"),
                        latency_s=round(time.time() - t0, 2),
                        tokens_in=usage.get("input_tokens", 0),
                        tokens_out=usage.get("output_tokens", 0),
                        searches=searches, usd=round(price_of(model, usage, searches), 5),
                        web_search=web_search,
                    ))
                    return data
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
        max_tool_calls: int | None = None,
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
            if max_tool_calls:
                body["max_tool_calls"] = max_tool_calls
        if max_output_tokens:
            body["max_output_tokens"] = max_output_tokens

        # hash the scrubbed body, so a blind run never reads a cached answer
        # that was produced with the target's name in the prompt
        body = self.scrub(body)
        key = hash_key(body)
        store = get_store()
        if use_cache and not settings.no_cache and (hit := store.cache_get(CACHE_NS, key)):
            self.budget.add_cached()
            resp = MetaResponse(**{**hit, "cached": True, "usd": 0.0})
            self._emit(MetaCall(agent_id=current_agent.get(), model=model,
                                response_id=resp.id, cached=True, web_search=web_search))
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

    # -------- agent loop with function tools
    async def run_tools(
        self,
        input: list,
        tools: list[Tool],
        *,
        instructions: str | None = None,
        schema: type[BaseModel] | None = None,
        effort: str = "low",
        model: str | None = None,
        max_turns: int = 16,
        on_call: Callable[[str, dict, Any], None] | None = None,
    ) -> MetaResponse:
        """Runs the model with function tools until it answers without calling one.
        The conversation is replayed statelessly each turn (verified Oct 30)."""
        model = model or settings.meta_model
        by_name = {t.name: t for t in tools}
        specs = [{"type": "function", "name": t.name, "description": t.description,
                  "parameters": strict_schema(t.params), "strict": True} for t in tools]
        convo = list(input)

        def _body(with_tools: bool) -> dict:
            b: dict[str, Any] = {"model": model, "input": convo, "reasoning": {"effort": effort}}
            if with_tools:
                b["tools"] = specs
            if instructions:
                b["instructions"] = instructions
            if schema is not None:
                b["text"] = {"format": {"type": "json_schema", "name": schema.__name__,
                                        "schema": strict_schema(schema), "strict": True}}
            return self.scrub(b)

        for _ in range(max_turns):
            body = _body(True)
            key = hash_key(body)
            store = get_store()
            if not settings.no_cache and (hit := store.cache_get(CACHE_NS + ".raw", key)) is not None:
                data = hit
                self.budget.add_cached()
                self._emit(MetaCall(agent_id=current_agent.get(), model=model,
                                    response_id=data.get("id"), cached=True))
            else:
                self.budget.check("llm")
                data = await self._post(body)
                self.budget.add_llm(model, data.get("usage") or {}, 0)
                store.cache_set(CACHE_NS + ".raw", key, data)
            out = data.get("output", [])
            calls = [o for o in out if o.get("type") == "function_call"]
            if not calls:
                text, anns, searches = _parse_output(data)
                return self._attach_parsed(MetaResponse(id=data.get("id"), model=model, text=text,
                                                        annotations=anns, usage=data.get("usage") or {}), schema)
            convo += out
            for c in calls:
                tool = by_name.get(c["name"])
                try:
                    # models sometimes write the string "null"/"None" for a null argument
                    raw = {k: (None if isinstance(v, str) and v.strip().lower() in ("null", "none", "") else v)
                           for k, v in json.loads(c.get("arguments") or "{}").items()}
                    args = tool.params.model_validate(raw) if tool else None
                    result = await tool.fn(args) if tool else {"error": f"unknown tool {c['name']}"}
                except Exception as e:  # noqa: BLE001
                    result = {"error": f"{type(e).__name__}: {e}"}
                if on_call:
                    on_call(c["name"], json.loads(c.get("arguments") or "{}"), result)
                convo.append({"type": "function_call_output", "call_id": c["call_id"],
                              "output": json.dumps(result, default=str)[:20000]})
        # Out of tool turns. Withdrawing the tools and asking once more turns a
        # long investigation into an answer, instead of throwing the work away:
        # a route argued from what was gathered beats no route at all.
        convo.append({"role": "user", "content":
                      "You have used all the research turns available. Give your final answer now, "
                      "from what you have already gathered. Do not call any more tools."})
        self.budget.check("llm")
        data = await self._post(_body(False))
        self.budget.add_llm(model, data.get("usage") or {}, 0)
        text, anns, _ = _parse_output(data)
        if not text:
            raise MetaAPIError(f"agent did not finish within {max_turns} tool turns, and gave no final answer")
        return self._attach_parsed(MetaResponse(id=data.get("id"), model=model, text=text,
                                                annotations=anns, usage=data.get("usage") or {}), schema)

    # -------- raw call used by SAM (different output grammar, image billing)
    async def raw(self, body: dict) -> dict:
        return await self._post(body)
