import os
import sys
from pathlib import Path

# Tests run offline and deterministically: no real LLM calls, no HF downloads.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LLM_API_KEY"] = ""          # force LLM-unavailable path in tests
os.environ["HF_HUB_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
