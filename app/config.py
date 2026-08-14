# -*- coding: utf-8 -*-
import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
TOP_K = int(os.getenv("RAG_TOP_K", "5"))
EXCERPT_CHARS = int(os.getenv("RAG_EXCERPT_CHARS", "600"))
DATA_DIR = BASE / os.getenv("RAG_DATA_DIR", "data")
MODEL_CACHE = BASE / os.getenv("RAG_MODEL_CACHE_DIR", "model_cache")
