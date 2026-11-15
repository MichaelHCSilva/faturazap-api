#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\ingestion.py

"""Leitura de documentos: transforma PDF, link de QR Code ou foto em um rascunho.

Nada é gravado no banco aqui. O rascunho só é salvo depois que o usuário confirma
a divisão na conversa (ver conversation.py).
"""
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src import config
from src.core import repository
from src.core.models import ReceiptData, StatementData
from src.core.repository import NewItem, NewStatement
from src.services import gemini_service
from src.services.gemini_service import GeminiError
from src.services.sefaz_scraper import fetch_page_text

logger = logging.getLogger(__name__)

_ACCESS_KEY_IN_URL = re.compile(r"(?<!\d)\d{44}(?!\d)")


class IngestionError(Exception):
    """Dados extraídos inválidos (ex.: valor total zerado, nenhum item)."""


@dataclass
class IngestionResult:
    status: str  # "success" | "duplicate" | "failed"
    statement: Optional[NewStatement] = None  # rascunho, só quando status == "success"
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
    if not data.items:
        raise IngestionError("Nenhum item foi encontrado no documento.")

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
    if not data.items:
        raise IngestionError("Nenhuma compra foi encontrada na fatura.")

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

def read_pdf(pdf_bytes: bytes) -> IngestionResult:
    """Fatura/boleto em PDF. O hash do arquivo identifica o documento (e evita gastar IA à toa)."""
    identifier = "pdf:" + hashlib.sha256(pdf_bytes).hexdigest()
    if repository.identifier_exists(identifier):
        return IngestionResult("duplicate")
    try:
        data = gemini_service.extract_statement_from_pdf(pdf_bytes)
        statement = _statement_from_pdf(data, identifier)
    except Exception as exc:
        logger.exception("Erro ao ler a fatura em PDF")
        return IngestionResult("failed", error=str(exc))
    return IngestionResult("success", statement)


def read_qrcode(url: str, owner_id: int) -> IngestionResult:
    """Link de QR Code da SEFAZ. Em caso de falha, o link vai para a fila de reprocessamento."""
    url_key = _access_key_from_url(url)
    if repository.identifier_exists(url_key):
        repository.delete_failed_qrcode(url)
        return IngestionResult("duplicate")

    try:
        page_text = fetch_page_text(url)
        data = gemini_service.extract_receipt_from_text(page_text)
        identifier = url_key or _normalize_access_key(data.access_key)
        if repository.identifier_exists(identifier):
            repository.delete_failed_qrcode(url)
            return IngestionResult("duplicate")
        statement = _receipt_to_statement(data, config.CARD_SEFAZ, qrcode=url, identifier=identifier)
    except Exception as exc:
        logger.exception("Erro ao ler o QR Code")
        _queue_failure(url, str(exc), owner_id)
        return IngestionResult("failed", error=str(exc))

    repository.delete_failed_qrcode(url)
    return IngestionResult("success", statement)


def read_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> IngestionResult:
    """Foto do cupom (Gemini Vision). A chave de 44 dígitos vira o identifier."""
    try:
        data = gemini_service.extract_receipt_from_image(image_bytes, mime_type)
        identifier = _normalize_access_key(data.access_key)
        if repository.identifier_exists(identifier):
            return IngestionResult("duplicate")
        statement = _receipt_to_statement(data, config.CARD_WHATSAPP, qrcode=None, identifier=identifier)
    except Exception as exc:
        logger.exception("Erro ao ler a foto do cupom")
        return IngestionResult("failed", error=str(exc))
    return IngestionResult("success", statement)


def reprocess_failed_qrcodes() -> tuple[dict[str, int], list[tuple[int, NewStatement]]]:
    """Tenta de novo os links da fila. Devolve a contagem e os rascunhos (dono, documento)."""
    counts = {"success": 0, "duplicate": 0, "failed": 0, "skipped": 0}
    ready: list[tuple[int, NewStatement]] = []
    for row in repository.list_failed_qrcodes():
        if row["owner_id"] is None:  # link antigo, sem dono para perguntar a divisão
            counts["skipped"] += 1
            continue
        result = read_qrcode(row["qrcode_url"], row["owner_id"])
        counts[result.status] += 1
        if result.status == "success":
            ready.append((row["owner_id"], result.statement))
    return counts, ready


def _queue_failure(url: str, error: str, owner_id: int) -> None:
    try:
        repository.save_failed_qrcode(url, error, owner_id)
    except Exception:
        logger.exception("Não foi possível gravar o link na fila de falhas")