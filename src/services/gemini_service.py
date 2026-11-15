#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\gemini_service.py
"""Todas as chamadas ao Gemini ficam aqui (PDF, texto da SEFAZ, foto e busca de endereço)."""
import logging
import re
from functools import lru_cache
from typing import Optional, TypeVar

from google import genai
from google.genai import types
from google.genai.errors import ServerError
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src import config
from src.core.models import ReceiptData, StatementData

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GeminiError(Exception):
    """Falha na chamada ao Gemini ou resposta fora do formato esperado."""


_RECEIPT_RULES = """
Extraia os dados de uma Nota Fiscal de Consumidor Eletrônica (NFC-e) brasileira.
Regras:
- store_name: nome do estabelecimento.
- cnpj: CNPJ do estabelecimento, somente dígitos (null se não constar).
- purchase_date: data da compra no formato DD/MM/AAAA.
- access_key: Chave de Acesso de 44 dígitos, somente dígitos (null se não constar).
- city, street: cidade e logradouro do estabelecimento.
- number: número do endereço exatamente como impresso; null se for "0", "S/N" ou ausente.
- total_amount: valor total a pagar.
- items: description é o nome limpo do produto (sem o nome do mercado) e amount o valor total do item.
Use null para o que não constar no documento. Não invente valores.
""".strip()

_STATEMENT_RULES = """
Analise esta fatura de cartão de crédito (ou boleto) em PDF e extraia os dados.
Regras:
- card_name: nome do banco ou cartão (ex.: Banco do Brasil, Carrefour, Senff).
- due_date: data de vencimento no formato DD/MM/AAAA.
- total_amount: valor total da fatura.
- barcode: código de barras ou linha digitável, se houver.
- pix_payload: payload do Pix (copia e cola), se houver.
- items: uma entrada por compra detalhada, com purchase_date (DD/MM/AAAA), description
  (nome do estabelecimento), city, street, number (quando constarem), amount e
  installment (ex.: "1/3"; null se for compra à vista).
Use null para o que não constar no documento. Não invente valores.
""".strip()


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(http_options={"api_version": config.GEMINI_API_VERSION})


@retry(
    retry=retry_if_exception_type((ServerError, GeminiError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _extract(contents: list, schema: type[T]) -> T:
    """Chama o Gemini pedindo JSON validado pelo schema e devolve o objeto já tipado."""
    try:
        response = _client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.0,
            ),
        )
    except ServerError as exc:
        logger.warning(f"Gemini indisponível (503), tentando novamente... Erro: {exc}")
        raise
    except Exception as exc:
        raise GeminiError(f"Falha ao chamar o Gemini: {exc}") from exc

    parsed = response.parsed
    if not isinstance(parsed, schema):
        raise GeminiError("O Gemini devolveu uma resposta fora do formato esperado.")
    return parsed


def extract_receipt_from_text(page_text: str) -> ReceiptData:
    """Interpreta o texto bruto da página da NFC-e na SEFAZ."""
    return _extract([_RECEIPT_RULES, f"TEXTO DA NOTA FISCAL:\n{page_text}"], ReceiptData)


def extract_receipt_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> ReceiptData:
    """Lê uma foto do cupom com o Gemini Vision."""
    image = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    return _extract([image, _RECEIPT_RULES], ReceiptData)


def extract_statement_from_pdf(pdf_bytes: bytes) -> StatementData:
    """Lê a fatura em PDF diretamente (o Gemini aceita PDF nativo, inclusive escaneado)."""
    pdf = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    return _extract([pdf, _STATEMENT_RULES], StatementData)


@retry(
    retry=retry_if_exception_type((ServerError, GeminiError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def lookup_address_number(
    cnpj: str, store_name: Optional[str], street: Optional[str], city: Optional[str]
) -> Optional[str]:
    """Busca na web o número oficial do endereço a partir do CNPJ. Retorna None se não achar."""
    prompt = (
        f"Use a busca na web para descobrir o número do endereço oficial do estabelecimento "
        f"com CNPJ {cnpj} (nome: {store_name or 'desconhecido'}; rua: {street or 'desconhecida'}; "
        f"cidade: {city or 'desconhecida'}). Responda SOMENTE com o número, apenas dígitos. "
        f"Se não encontrar com segurança, responda NAO_ENCONTRADO."
    )
    try:
        response = _client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,
            ),
        )
    except ServerError as exc:
        logger.warning(f"Gemini indisponível na busca de endereço (503), tentando novamente... Erro: {exc}")
        raise
    except Exception as exc:
        raise GeminiError(f"Falha na busca do endereço: {exc}") from exc

    answer = re.sub(r"\W", "", response.text or "")
    if answer.isdigit() and int(answer) > 0:
        return answer
    return None