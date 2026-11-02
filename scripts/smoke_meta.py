"""Smoke-test the Meta Model API shapes we depend on.

Run:  .venv/Scripts/python scripts/smoke_meta.py [test ...]
Tests: text, structured, search, search_structured, vision, sam
Raw responses are written to scripts/_smoke_out/<test>.json for inspection.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scripts" / "_smoke_out"
OUT.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")

KEY = os.getenv("META_API_KEY") or os.getenv("MODEL_API_KEY")
BASE = os.getenv("META_BASE_URL", "https://api.meta.ai/v1")
MODEL = os.getenv("META_MODEL", "muse-spark-1.3")
SAM = os.getenv("SAM_MODEL", "sam-3.1")


def post(name: str, body: dict, timeout: float = 180) -> dict:
    t0 = time.time()
    r = httpx.post(
        f"{BASE}/responses",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    dt = time.time() - t0
    try:
        data = r.json()
    except Exception:
        data = {"_raw": r.text}
    (OUT / f"{name}.json").write_text(json.dumps({"request": _redact(body), "status": r.status_code, "response": data}, indent=2))
    print(f"  HTTP {r.status_code} in {dt:.1f}s  usage={data.get('usage') if isinstance(data, dict) else None}")
    if r.status_code >= 400:
        raise RuntimeError(json.dumps(data)[:800])
    return data


def _redact(body: dict) -> dict:
    s = json.dumps(body)
    s = re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "data:image/png;base64,<…>", s)
    return json.loads(s)


def output_text(resp: dict, last_only: bool = True) -> str:
    """Tool-using responses contain several message items (progress preambles);
    the final answer / structured JSON is the last one."""
    msgs = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            msgs.append("".join(c.get("text", "") for c in item.get("content", []) if c.get("type") == "output_text"))
    if not msgs:
        return ""
    return msgs[-1] if last_only else "".join(msgs)


def annotations(resp: dict) -> list[dict]:
    out = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                out.extend(c.get("annotations") or [])
    return out


def png_data_url(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- tests

def t_text():
    r = post("text", {"model": MODEL, "input": "Reply with exactly: ORCHANIUM_OK"})
    txt = output_text(r)
    print("  ->", txt[:200])
    assert "ORCHANIUM_OK" in txt


EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reactions"],
    "properties": {
        "reactions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["reactants", "products", "reagents", "conditions"],
                "properties": {
                    "reactants": {"type": "array", "items": {"type": "string"}},
                    "products": {"type": "array", "items": {"type": "string"}},
                    "reagents": {"type": "array", "items": {"type": "string"}},
                    "conditions": {"type": ["string", "null"]},
                },
            },
        }
    },
}


def t_structured():
    r = post("structured", {
        "model": MODEL,
        "input": "Extract the reaction(s): Aspirin is made by treating salicylic acid with acetic anhydride "
                 "in the presence of a catalytic amount of sulfuric acid at 85 °C; acetic acid is a by-product.",
        "text": {"format": {"type": "json_schema", "name": "reactions", "schema": EXTRACT_SCHEMA, "strict": True}},
    })
    data = json.loads(output_text(r))
    print("  ->", json.dumps(data)[:300])
    assert data["reactions"]


def t_search():
    r = post("search", {
        "model": MODEL,
        "input": "Find published laboratory or industrial syntheses of paracetamol (acetaminophen). "
                 "For each, state reactants, reagents, conditions, and cite the source.",
        "tools": [{"type": "web_search", "search_context_size": "high"}],
        "include": ["web_search_call.results"],
    }, timeout=300)
    anns = annotations(r)
    calls = [o for o in r.get("output", []) if o.get("type") == "web_search_call"]
    n_results = sum(len(c.get("results") or []) for c in calls)
    print(f"  -> {len(calls)} web_search_call items, {n_results} results, {len(anns)} url_citation annotations")
    print("  -> output item keys:", [sorted(o.keys()) for o in calls][:2])
    for a in anns[:4]:
        print("     cite:", a.get("title"), a.get("url"))
    for c in calls[:1]:
        for res in (c.get("results") or [])[:3]:
            print("     result:", res.get("title"), "|", (res.get("snippet") or "")[:100])
    print("  -> text:", output_text(r)[:300].replace("\n", " "))
    assert anns or n_results


def t_search_structured():
    schema = {
        "type": "object", "additionalProperties": False, "required": ["routes"],
        "properties": {"routes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["reactants", "products", "source_url"],
            "properties": {
                "reactants": {"type": "array", "items": {"type": "string"}},
                "products": {"type": "array", "items": {"type": "string"}},
                "source_url": {"type": "string"},
            }}}},
    }
    r = post("search_structured", {
        "model": MODEL,
        "input": "Search the web for the BHC synthesis of ibuprofen and list each step with a source URL.",
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.results"],
        "text": {"format": {"type": "json_schema", "name": "routes", "schema": schema, "strict": True}},
    }, timeout=300)
    data = json.loads(output_text(r))
    print("  ->", json.dumps(data)[:400])


def t_vision():
    from rdkit import Chem
    from rdkit.Chem import Draw
    img = Draw.MolToImage(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"), size=(400, 400))
    schema = {"type": "object", "additionalProperties": False, "required": ["name", "smiles", "confidence"],
              "properties": {"name": {"type": "string"}, "smiles": {"type": "string"}, "confidence": {"type": "number"}}}
    r = post("vision", {
        "model": MODEL,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "Identify this chemical structure drawing. Give its common name and SMILES."},
            {"type": "input_image", "image_url": png_data_url(img)},
        ]}],
        "text": {"format": {"type": "json_schema", "name": "mol", "schema": schema, "strict": True}},
    })
    print("  ->", output_text(r))


SAM_RE = re.compile(r"<(\d+)f>(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+)[^|]*\|>")


def t_sam():
    from rdkit.Chem import AllChem, Draw
    rxn = AllChem.ReactionFromSmarts("Oc1ccccc1C(=O)O.CC(=O)OC(C)=O>>CC(=O)Oc1ccccc1C(=O)O", useSmiles=True)
    img = Draw.ReactionToImage(rxn, subImgSize=(300, 300))
    img.save(OUT / "sam_input.png")
    for prompt in ["chemical structure", "molecule drawing", "arrow"]:
        print(f"  prompt={prompt!r}")
        r = post(f"sam_{prompt.replace(' ', '_')}", {
            "model": SAM,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": png_data_url(img)},
            ]}],
            "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
        })
        txt = output_text(r)
        boxes = SAM_RE.findall(txt)
        print(f"  -> {len(boxes)} objects; image {img.size}; first 200 chars: {txt[:200]!r}")
        for b in boxes:
            print("     box", b[2:])


TESTS = {"text": t_text, "structured": t_structured, "search": t_search,
         "search_structured": t_search_structured, "vision": t_vision, "sam": t_sam}

if __name__ == "__main__":
    if not KEY:
        sys.exit("No META_API_KEY / MODEL_API_KEY in .env")
    names = sys.argv[1:] or list(TESTS)
    results = {}
    for n in names:
        print(f"\n=== {n}")
        try:
            TESTS[n]()
            results[n] = "OK"
        except Exception as e:  # noqa: BLE001
            results[n] = f"FAIL: {e}"
            print("  !!", str(e)[:800])
    print("\n=== summary")
    for n, s in results.items():
        print(f"  {'✓' if s == 'OK' else '✗'} {n}: {s[:200]}")
