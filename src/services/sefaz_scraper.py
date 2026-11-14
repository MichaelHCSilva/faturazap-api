#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\sefaz_scraper.py
"""Download e limpeza da página da NFC-e na SEFAZ."""
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src import config


class ScraperError(Exception):
    """Não foi possível obter o conteúdo do cupom."""


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host.endswith(config.ALLOWED_QRCODE_HOST_SUFFIXES):
        raise ScraperError("Link fora dos domínios fiscais permitidos.")


def fetch_page_text(url: str) -> str:
    """Baixa a página do cupom e devolve só o texto visível."""
    _validate_url(url)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": config.SEFAZ_USER_AGENT},
            timeout=config.SEFAZ_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Falha ao acessar a SEFAZ: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    if not text:
        raise ScraperError("A página da SEFAZ veio vazia.")
    return text[: config.MAX_PAGE_TEXT_CHARS]