"""SAM 3.1 via the Meta Model API. We only need boxes (for cropping), so masks
are requested in the compact one-bit encoding and ignored.

Verified behaviour (Oct 30): on reaction-scheme images a concept prompt such as
"chemical structure" returns the single best instance per call. `find_all`
therefore runs find -> white-out -> re-query until nothing is left."""
from __future__ import annotations

import base64
import io
import re

from PIL import Image, ImageDraw
from pydantic import BaseModel

from ..config import settings
from ..store import get_store, hash_key
from .client import MetaClient

_RECORD = re.compile(r"<(\d+)f>(\d+)<\|box;([^|]*)\|>")
CACHE_NS = "sam.v1"


class SamBox(BaseModel):
    frame: int
    ordinal: int
    x1: int
    y1: int
    x2: int
    y2: int
    w: int
    h: int
    confidence: float | None = None

    @property
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)


def parse_sam_output(text: str) -> list[SamBox]:
    out = []
    for frame, ordinal, fields in _RECORD.findall(text or ""):
        kv = dict(f.split("=", 1) for f in fields.split(";") if "=" in f)
        try:
            out.append(SamBox(frame=int(frame), ordinal=int(ordinal),
                              x1=int(kv["x1"]), y1=int(kv["y1"]), x2=int(kv["x2"]), y2=int(kv["y2"]),
                              w=int(kv.get("w", 0)), h=int(kv.get("h", 0)),
                              confidence=float(kv["c"]) if "c" in kv else None))
        except (KeyError, ValueError):
            continue
    return out


def to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def segment(client: MetaClient, img: Image.Image, prompt: str) -> list[SamBox]:
    data_url = to_data_url(img)
    body = {
        "model": settings.sam_model,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": data_url},
        ]}],
        "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
    }
    key = hash_key({"prompt": prompt, "img": hash_key(data_url), "model": settings.sam_model})
    store = get_store()
    if (hit := store.cache_get(CACHE_NS, key)) is not None:
        return [SamBox(**b) for b in hit]
    client.budget.check("sam")
    data = await client.raw(body)
    client.budget.add_sam(1)
    text = "".join(c.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
                   for c in item.get("content", []) if c.get("type") == "output_text")
    boxes = parse_sam_output(text)
    store.cache_set(CACHE_NS, key, [b.model_dump() for b in boxes])
    return boxes


async def find_all(client: MetaClient, img: Image.Image, prompt: str = "chemical structure",
                   max_objects: int = 8, min_conf: float = 0.3, pad: int = 6) -> list[SamBox]:
    """Iteratively find every instance: detect, white out, detect again."""
    work = img.convert("RGB").copy()
    found: list[SamBox] = []
    for _ in range(max_objects):
        boxes = [b for b in await segment(client, work, prompt) if (b.confidence or 1) >= min_conf]
        if not boxes:
            break
        draw = ImageDraw.Draw(work)
        for b in boxes:
            found.append(b)
            draw.rectangle((b.x1 - pad, b.y1 - pad, b.x2 + pad, b.y2 + pad), fill="white")
    return found


def crop(img: Image.Image, b: SamBox, pad: int = 8) -> Image.Image:
    return img.crop((max(0, b.x1 - pad), max(0, b.y1 - pad),
                     min(img.width, b.x2 + pad), min(img.height, b.y2 + pad)))
