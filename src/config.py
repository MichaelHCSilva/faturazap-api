#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\config.py
"""Configurações centrais do FaturaZap."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Pasta dos dados (banco e uploads). Pode ser trocada pela variável FATURAZAP_DATA_DIR,
# o que permite guardar o banco fora de pastas sincronizadas (OneDrive) ou de /mnt/c no WSL.
DATA_DIR = Path(os.getenv("FATURAZAP_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "faturazap.db"

# Gemini (a chave é lida da variável de ambiente GEMINI_API_KEY ou GOOGLE_API_KEY)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_VERSION = "v1beta"

# Scraping da SEFAZ
SEFAZ_TIMEOUT_SECONDS = 15
SEFAZ_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Só aceita links de domínios fiscais (evita que o webhook seja usado para acessar URLs arbitrárias).
ALLOWED_QRCODE_HOST_SUFFIXES = (".gov.br",)
MAX_PAGE_TEXT_CHARS = 60_000

# API
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Documentos lidos que ainda não foram confirmados (ficam só em memória) expiram depois disto.
DRAFT_TTL_SECONDS = 24 * 60 * 60

# Nomes das "origens" usadas na tabela cards
CARD_SEFAZ = "Cupom Fiscal / SEFAZ"
CARD_WHATSAPP = "Cupom Fiscal / WhatsApp"