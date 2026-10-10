"""Settings loaded from environment (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]


def _b(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else ROOT / p


@dataclass
class Settings:
    # LLM
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://neo-hackathon.services.ai.azure.com/openai/v1/")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "Neo-Hackathon")
    llm_reasoning_effort: str = os.getenv("LLM_REASONING_EFFORT", "low")
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "30"))

    # Paths
    db_path: Path = _path("DB_PATH", "data/ridewise.db")
    docs_dir: Path = _path("DOCS_DIR", "data")
    index_dir: Path = _path("INDEX_DIR", "data/index")
    transcriptions_dir: Path = _path("TRANSCRIPTIONS_DIR", "data/transcriptions")
    chat_dir: Path = _path("CHAT_DIR", "data/chat_history")

    # Retrieval
    embeddings_enabled: bool = _b("EMBEDDINGS_ENABLED", True)
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
    supabase_db_url: str = os.getenv("SUPABASE_DB_URL", "")

    # Optional features
    web_search_enabled: bool = _b("WEB_SEARCH_ENABLED", False)
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    # Staff (agent) login
    agent_id: str = os.getenv("AGENT_ID", "agent")
    agent_pw_hash: str = os.getenv("AGENT_PW_HASH", "")

    # Tracing
    langsmith_tracing: bool = _b("LANGSMITH_TRACING", False)

    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    def llm_endpoint(self) -> str:
        return self.llm_base_url


settings = Settings()
