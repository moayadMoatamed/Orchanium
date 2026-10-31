from pydantic import BaseModel

from orchanium.meta.client import _parse_output, normalize_url, strict_schema
from orchanium.meta.sam import parse_sam_output


def test_parse_sam_output_with_confidence():
    text = ("<0f>0<|box;x1=789;y1=24;x2=1101;y2=274;w=1200;h=300;c=0.84|><|mask;x=0;y=0;c=0.84;data=251,313,!!!|>,"
            "<0f>1<|box;x1=97;y1=51;x2=362;y2=248;w=1200;h=300|><|mask;x=0;y=0;data=1,2,!|>\n")
    boxes = parse_sam_output(text)
    assert [(b.ordinal, b.x1, b.y2) for b in boxes] == [(0, 789, 274), (1, 97, 248)]
    assert boxes[0].confidence == 0.84 and boxes[1].confidence is None
    assert parse_sam_output("") == []


class Inner(BaseModel):
    name: str
    yield_pct: float | None = None


class Outer(BaseModel):
    items: list[Inner]
    note: str = "x"


def test_strict_schema_closes_objects_and_inlines_refs():
    s = strict_schema(Outer)
    assert "$defs" not in s and s["additionalProperties"] is False
    assert s["required"] == ["items", "note"]
    inner = s["properties"]["items"]["items"]
    assert inner["additionalProperties"] is False and inner["required"] == ["name", "yield_pct"]
    assert "default" not in s["properties"]["note"]


def test_parse_output_uses_last_message_and_collects_searches():
    data = {"output": [
        {"type": "message", "content": [{"type": "output_text", "text": "Searching...", "annotations": []}]},
        {"type": "web_search_call", "action": {"type": "search", "query": "aspirin synthesis"},
         "results": [{"type": "text_result", "title": "T", "url": "https://Www.Example.Com/Path", "snippet": ""}]},
        {"type": "message", "content": [{"type": "output_text", "text": '{"a": 1}', "annotations": [
            {"type": "url_citation", "url": "https://Www.Mdpi.Com/X", "title": "M", "start_index": 0, "end_index": 3}]}]},
    ]}
    text, anns, searches = _parse_output(data)
    assert text == '{"a": 1}'
    assert anns[0]["url"] == "https://www.mdpi.com/X"
    assert searches[0].query == "aspirin synthesis"
    assert searches[0].results[0]["url"] == "https://www.example.com/Path"


def test_normalize_url_keeps_path_case():
    assert normalize_url("HTTPS://PubChem.NCBI.nlm.nih.gov/Compound/Aspirin") == \
        "https://pubchem.ncbi.nlm.nih.gov/Compound/Aspirin"


class HasTitleField(BaseModel):
    title: str
    default: int


def test_strict_schema_keeps_fields_named_title_and_default():
    s = strict_schema(HasTitleField)
    assert set(s["properties"]) == {"title", "default"}
    assert s["required"] == ["title", "default"]
    assert "title" not in s["properties"]["title"]          # annotation stripped inside


def test_agent_out_of_tool_turns_still_answers(monkeypatch):
    """A long investigation must end in a result: when the turns run out the
    tools are withdrawn and the model is asked for its answer."""
    import asyncio
    from pydantic import BaseModel
    from orchanium.meta.client import Budget, MetaClient, Tool

    class Args(BaseModel):
        q: str

    class Out(BaseModel):
        answer: str

    calls = {"tool_bodies": 0, "final_bodies": 0}

    async def fake_post(body, attempts=3):
        if "tools" in body:
            calls["tool_bodies"] += 1
            return {"id": "x", "usage": {},
                    "output": [{"type": "function_call", "name": "look", "call_id": f"c{calls['tool_bodies']}",
                                "arguments": '{"q": "more"}'}]}
        calls["final_bodies"] += 1
        return {"id": "y", "usage": {},
                "output": [{"type": "message", "content": [{"type": "output_text",
                                                            "text": '{"answer": "from what I gathered"}'}]}]}

    class NoCache:
        def cache_get(self, *a):
            return None

        def cache_set(self, *a):
            return None

    monkeypatch.setattr("orchanium.meta.client.get_store", lambda: NoCache())
    client = MetaClient.__new__(MetaClient)
    client.budget, client.redact = Budget(), None
    monkeypatch.setattr(client, "_post", fake_post)
    tool = Tool(name="look", description="look", params=Args, fn=lambda a: _ok())

    async def _ok():
        return {"ok": True}

    resp = asyncio.run(client.run_tools([{"role": "user", "content": "go"}], [tool],
                                        schema=Out, max_turns=3))
    assert calls["tool_bodies"] == 3 and calls["final_bodies"] == 1
    assert resp.parsed.answer == "from what I gathered"
