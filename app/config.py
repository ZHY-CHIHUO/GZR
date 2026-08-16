# -*- coding: utf-8 -*-
import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.getenv("GZR_ENV_FILE", BASE / ".env"))
load_dotenv(ENV_FILE)

KEY = os.getenv("AI_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")).strip()
BASE_URL = os.getenv(
    "AI_BASE_URL",
    os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
).strip()
MODEL = os.getenv(
    "AI_MODEL",
    os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
).strip()
TOP_K = int(os.getenv("RAG_TOP_K", "5"))
EXCERPT_CHARS = int(os.getenv("RAG_EXCERPT_CHARS", "600"))
# 检索库固定为 Jina 中文增强版本；项目不再保留可切换的其他向量模型。
DATA_DIR = BASE / "data_jina2"
MODEL_CACHE = BASE / os.getenv("RAG_MODEL_CACHE_DIR", "model_cache")


def _set_env_var(name: str, value: str) -> None:
    """写回 .env（替换或追加），并同步内存。"""
    global KEY, BASE_URL, MODEL
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith(name + "="):
            lines[i] = f"{name}={value}"
            found = True
    if not found:
        lines.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[name] = value
    if name == "AI_API_KEY":
        KEY = value.strip()
    elif name == "AI_BASE_URL":
        BASE_URL = value.strip()
    elif name == "AI_MODEL":
        MODEL = value.strip()


def set_api_key(key: str) -> None:
    _set_env_var("AI_API_KEY", key.strip())


def set_base_url(base_url: str) -> None:
    _set_env_var("AI_BASE_URL", base_url.strip())


def set_model(model: str) -> None:
    _set_env_var("AI_MODEL", model.strip() or "deepseek-chat")
