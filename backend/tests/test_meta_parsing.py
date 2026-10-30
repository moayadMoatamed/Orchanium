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
