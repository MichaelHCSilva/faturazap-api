#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\ingestion.py

"""Casos de uso: transformam PDF, link de QR Code ou foto em extratos salvos no banco."""
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src import config
from src.core import repository
from src.core.models import ReceiptData, StatementData
from src.core.repository import DuplicateStatementError, NewItem, NewStatement
from src.services import gemini_service
from src.services.gemini_service import GeminiError
from src.services.sefaz_scraper import fetch_page_text

logger = logging.getLogger(__name__)

_ACCESS_KEY_IN_URL = re.compile(r"(?<!\d)\d{44}(?!\d)")


class IngestionError(Exception):
    """Dados extraídos inválidos (ex.: valor total zerado)."""


@dataclass
class IngestionResult:
    status: str  # "success" | "duplicate" | "failed"
    store_name: Optional[str] = None
    total_amount: Optional[float] = None
    error: Optional[str] = None


# --- Helpers -----------------------------------------------------------------------

def _today() -> str:
    return date.today().strftime("%d/%m/%Y")


def _valid_number(number: Optional[str]) -> Optional[str]:
    """Descarta placeholders ("0", "S/N", vazio): número válido tem algum dígito de 1 a 9."""
    if number and re.search(r"[1-9]", str(number)):
        return str(number).strip()
    return None


def _normalize_access_key(value: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", value or "")
    return digits if len(digits) == 44 else None


def _access_key_from_url(url: str) -> Optional[str]:
    match = _ACCESS_KEY_IN_URL.search(url)
    return match.group() if match else None


def _resolve_address_number(data: ReceiptData) -> Optional[str]:
    """Usa o número impresso; se for inválido, tenta achar o oficial pelo CNPJ (busca web)."""
    number = _valid_number(data.number)
    if number or not data.cnpj:
        return number
    try:
        return gemini_service.lookup_address_number(
            data.cnpj, data.store_name, data.street, data.city
        )
    except GeminiError:
        logger.warning("Não foi possível validar o endereço pelo CNPJ %s", data.cnpj, exc_info=True)
        return None


def _receipt_to_statement(
    data: ReceiptData, card_name: str, qrcode: Optional[str], identifier: Optional[str]
) -> NewStatement:
    total = round(data.total_amount or 0.0, 2)
    if total <= 0:
        raise IngestionError("O valor total extraído é inválido ou zerado.")

    purchase_date = data.purchase_date or _today()
    number = _resolve_address_number(data)
    items = [
        NewItem(
            purchase_date=purchase_date,
            description=(item.description or "").strip() or "Item sem descrição",
            amount=round(item.amount or 0.0, 2),
            city=data.city,
            street=data.street,
            number=number,
        )
        for item in data.items
    ]
    return NewStatement(
        card_name=card_name,
        store_name=data.store_name,
        due_date=purchase_date,
        total_amount=total,
        qrcode=qrcode,
        identifier=identifier,
        items=items,
    )


def _statement_from_pdf(data: StatementData, identifier: str) -> NewStatement:
    total = round(data.total_amount or 0.0, 2)
    if total <= 0:
        raise IngestionError("O valor total da fatura é inválido ou zerado.")

    fallback_date = data.due_date or _today()
    items = [
        NewItem(
            purchase_date=item.purchase_date or fallback_date,
            description=(item.description or "").strip() or "Sem descrição",
            amount=round(item.amount or 0.0, 2),
            city=item.city,
            street=item.street,
            number=_valid_number(item.number),
            installment=item.installment,
        )
        for item in data.items
    ]
    return NewStatement(
        card_name=(data.card_name or "").strip() or "Desconhecido",
        due_date=data.due_date,
        total_amount=total,
        barcode=data.barcode,
        qrcode=data.pix_payload,
        identifier=identifier,
        items=items,
    )


# --- Casos de uso ------------------------------------------------------------------

def process_pdf(pdf_bytes: bytes) -> IngestionResult:
    """Fatura/boleto em PDF. O hash do arquivo impede salvar o mesmo PDF duas vezes."""
    identifier = "pdf:" + hashlib.sha256(pdf_bytes).hexdigest()
    try:
        data = gemini_service.extract_statement_from_pdf(pdf_bytes)
        statement = _statement_from_pdf(data, identifier)
        repository.save_statement(statement)
    except DuplicateStatementError:
        return IngestionResult("duplicate")
    except Exception as exc:
        logger.exception("Erro ao processar a fatura em PDF")
        return IngestionResult("failed", error=str(exc))
    return IngestionResult("success", statement.card_name, statement.total_amount)


def process_qrcode(url: str) -> IngestionResult:
    """Link de QR Code da SEFAZ. Em caso de falha, o link vai para a fila de reprocessamento."""
    try:
        page_text = fetch_page_text(url)
        data = gemini_service.extract_receipt_from_text(page_text)
        identifier = _access_key_from_url(url) or _normalize_access_key(data.access_key)
        statement = _receipt_to_statement(data, config.CARD_SEFAZ, qrcode=url, identifier=identifier)
        repository.save_statement(statement)
    except DuplicateStatementError:
        repository.delete_failed_qrcode(url)
        return IngestionResult("duplicate")
    except Exception as exc:
        logger.exception("Erro ao processar o QR Code")
        _queue_failure(url, str(exc))
        return IngestionResult("failed", error=str(exc))

    repository.delete_failed_qrcode(url)
    return IngestionResult("success", statement.store_name, statement.total_amount)


def process_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> IngestionResult:
    """Foto do cupom (Gemini Vision). A chave de 44 dígitos vira o identifier."""
    try:
        data = gemini_service.extract_receipt_from_image(image_bytes, mime_type)
        identifier = _normalize_access_key(data.access_key)
        statement = _receipt_to_statement(data, config.CARD_WHATSAPP, qrcode=None, identifier=identifier)
        repository.save_statement(statement)
    except DuplicateStatementError:
        return IngestionResult("duplicate")
    except Exception as exc:
        logger.exception("Erro ao processar a foto do cupom")
        return IngestionResult("failed", error=str(exc))
    return IngestionResult("success", statement.store_name, statement.total_amount)


def reprocess_failed_qrcodes() -> dict[str, int]:
    """Tenta de novo todos os links da fila e devolve a contagem por resultado."""
    summary = {"success": 0, "duplicate": 0, "failed": 0}
    for url in repository.list_failed_qrcodes():
        summary[process_qrcode(url).status] += 1
    return summary


def _queue_failure(url: str, error: str) -> None:
    try:
        repository.save_failed_qrcode(url, error)
    except Exception:
        logger.exception("Não foi possível gravar o link na fila de falhas")