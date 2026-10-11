"""Runtime configuration loaded from environment / .env file."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# OpenAI-compatible endpoints we have tested the agent with.
PROVIDERS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
}

DEFAULT_MODELS = {
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "gemini": "gemini-3.6-flash",
    "groq": "llama-3.3-70b-versatile",
    "ollama": "qwen2.5:7b",
}

# Tried in order when the main model is overloaded or not available.
BACKUP_MODELS = {
    "gemini": ["gemini-3.5-flash", "gemini-3.5-flash-lite"],
    "openrouter": ["google/gemma-3-27b-it:free"],
}


@dataclass
class Settings:
    provider: str
    base_url: str
    api_key: str
    model: str
    max_steps: int = 20
    temperature: float = 0.1
    log_dir: Path = ROOT / "logs"
    memory_dir: Path = ROOT / "memory"
    output_dir: Path = ROOT / "outputs"


def load_settings(**overrides) -> Settings:
    provider = overrides.get("provider") or os.getenv("LLM_PROVIDER", "openrouter")
    base_url = overrides.get("base_url") or os.getenv("LLM_BASE_URL") or PROVIDERS.get(provider, PROVIDERS["openrouter"])
    api_key = overrides.get("api_key") or os.getenv("LLM_API_KEY", "")
    if provider == "ollama" and not api_key:
        api_key = "ollama"  # local server ignores the key
    model = overrides.get("model") or os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openrouter"])
    s = Settings(provider=provider, base_url=base_url, api_key=api_key, model=model)
    if overrides.get("max_steps"):
        s.max_steps = int(overrides["max_steps"])
    for d in (s.log_dir, s.memory_dir, s.output_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
