import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Tests run offline and deterministically: no real LLM calls, no HF downloads.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LLM_API_KEY"] = ""          # force LLM-unavailable path in tests
os.environ["SUPABASE_DB_URL"] = ""      # tests use the local store (no network)
os.environ["WEB_SEARCH_ENABLED"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"

# Deterministic staff credentials for auth tests (set before ridewise.config import).
os.environ["AGENT_ID"] = "agent"
from ridewise.auth import hash_password  # noqa: E402  (does not import config)
os.environ["AGENT_PW_HASH"] = hash_password("test-staff-pass-123")

TEST_STAFF_PASSWORD = "test-staff-pass-123"
