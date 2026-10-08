"""Configuration loader.

Reads credentials from the local .env file (gitignored). Never prints values.
Copy config.example -> .env and fill in the real class API key.
"""
import os

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(_REPO_ROOT, ".env")

REPO_ROOT = _REPO_ROOT
MATERIALS_DIR = os.path.join(_REPO_ROOT, "materials")
RESULTS_DIR = os.path.join(_REPO_ROOT, "results")
INDEX_DIR = os.path.join(_REPO_ROOT, "index")
RENDERS_DIR = os.path.join(_REPO_ROOT, "renders")


def _load_env() -> dict:
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


_ENV = _load_env()

# Class API key (server-side only; never expose in UI/logs/docs/GitHub)
CLASS_API_KEY = _ENV.get("CLASS_API_KEY", "")
LLM_BASE = _ENV.get("LLM_BASE", "http://localhost:9001/v1")
TEXT_EMBED_BASE = _ENV.get("TEXT_EMBED_BASE", "http://localhost:9002")
VISUAL_EMBED_BASE = _ENV.get("VISUAL_EMBED_BASE", "http://localhost:9003/v1")
RERANK_BASE = _ENV.get("RERANK_BASE", "http://localhost:9004")
PARSE_BASE = _ENV.get("PARSE_BASE", "http://localhost:9005/v1")


def ensure_configured() -> None:
    """Raise a clear error when .env is missing or the key is a dummy."""
    if not CLASS_API_KEY or CLASS_API_KEY.startswith("sk-"):  # dummy values start with sk-
        raise RuntimeError(
            "No real class API key configured: copy config.example to .env and "
            "fill in the real key (see README)."
        )
