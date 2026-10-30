from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PROMPTS = BACKEND / "prompts"
DATA = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    meta_api_key: str = Field("", validation_alias=AliasChoices("META_API_KEY", "MODEL_API_KEY"))
    meta_base_url: str = "https://api.meta.ai/v1"
    meta_model: str = "muse-spark-1.3"
    meta_model_cheap: str = "muse-spark-1.3"
    sam_model: str = "sam-3.1"

    db_path: Path = DATA / "orchanium.sqlite"
    fetch_contact_url: str = ""          # put in the citation-checker User-Agent (Wikipedia requires one)

    # per-run guardrails
    max_llm_calls: int = 80
    max_searches: int = 40
    max_tokens: int = 4_000_000
    max_usd: float = 2.50                # hard per-run spend cap
    searches_per_research: int = 6       # web searches one research call may run
    max_sam_images: int = 20
    max_researchers: int = 5
    max_followup_depth: int = 2
    max_route_depth: int = 6
    max_proposals_per_gap: int = 3
    agent_timeout_s: float = 240.0

    # USD per 1M tokens / per unit (dev.meta.ai pricing page, Oct 2026)
    price: dict[str, tuple[float, float, float]] = {
        # model: (input, cached_input, output)
        "muse-spark-1.3": (1.25, 0.15, 4.25),
        "muse-spark-1.3-contributor": (0.10, 0.002, 0.20),
        "muse-wonder-1.0": (4.00, 0.20, 20.00),
    }
    price_per_search: float = 2.50 / 1000
    price_per_sam_image: float = 2.50 / 1000


settings = Settings()
DATA.mkdir(exist_ok=True)
