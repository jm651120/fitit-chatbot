"""Central configuration for the FitIt chatbot."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Paths ---
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
LOGS_DIR = DATA_DIR / "logs"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

for _d in (RAW_DIR, PROCESSED_DIR, LOGS_DIR, CHROMA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Site ---
BASE_URL = "https://fitit.pt"
SITE_NAME = "FIT IT"
CONTACT_URL = "https://fitit.pt/contactos/"
CRAWL_LIMIT = 60

# --- API keys / models ---
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# Tried in order until one answers (Groq decommissions models periodically;
# llama-3.1-70b-versatile is already gone, llama-3.3-70b-versatile is its successor).
GROQ_MODEL_FALLBACKS = [
    GROQ_MODEL,
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
]
# Small fast model used for query rewriting (follow-up condensation).
GROQ_REWRITE_MODEL = "llama-3.1-8b-instant"

# Multilingual variant: the site and all queries are in Portuguese, and the
# English-only all-MiniLM-L6-v2 ranks PT text noticeably worse (validated
# empirically). Same 384 dims, same API.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# --- ChromaDB collections ---
COLLECTION_SCHEDULE = "schedule"
COLLECTION_PRICING = "pricing"
COLLECTION_GENERAL = "general"
ALL_COLLECTIONS = [COLLECTION_SCHEDULE, COLLECTION_PRICING, COLLECTION_GENERAL]

# --- Scheduling ---
TIMEZONE = "Europe/Lisbon"

# --- Crawl URL selection ---
# Stale marketing campaigns, thank-you pages and form endpoints add noise
# (and outdated promo prices) to the index, so they are skipped.
EXCLUDE_URL_PATTERNS = [
    "-obrigado", "obrigado-", "/obrigado", "campanha-", "black-",
    "dezembro2021", "so-faltas-tu", "oferta-exclusiva", "50-ate-final",
    "4-meses-gratis", "dia-de-treino-gratis", "pack-verao", "verao-fit",
    "treina-com", "traz-um-amigo", "earlybird", "voucher-to-api",
    "/sair", "modalidades-teste", "plano-fit-60", "ebook-",
]

# Crawled first, in this order, before any blog post fills the remaining budget.
PRIORITY_SLUGS = [
    "",  # homepage
    "mapa-de-aulas",
    "servicos",
    "inscricao",
    "contactos",
    "quem-somos",
    "modalidades",
    "forca",
    "resistencia",
    "body-mind",
    "mobilidade",
    "fun",
    "kids",
    "box-fit-it",
    "small-group-indoor",
    "modalidade/bodymind",
    "fitemcasa",
    "corporate",
    "empresas",
    "parcerias",
    "parceria",
    "treino-experimental",
    "voucher",
    "planos-off-peak",
    "fitit-max",
    "pack-familia",
    "recrutamento",
    "blog",
    "condicoes-contratuais",
    "politica-de-privacidade",
]

# Slug -> page_type hints (content heuristics refine these further).
SCHEDULE_SLUGS = {"mapa-de-aulas"}
PRICING_SLUGS = {
    "inscricao", "planos-off-peak", "fitit-max",
    "pack-familia", "voucher", "treino-experimental",
}
CLASSES_SLUGS = {
    "modalidades", "forca", "resistencia", "body-mind", "mobilidade",
    "fun", "kids", "box-fit-it", "small-group-indoor", "fitemcasa",
}

# --- Brand (extracted from fitit.pt inline Elementor styles) ---
BRAND = {
    "gold": "#daa360",
    "gold_dark": "#c19a6b",
    "purple": "#58449a",
    "dark": "#16131a",
    "card": "#221f20",
    "text": "#f2efe9",
    "muted": "#9ea0a4",
}
