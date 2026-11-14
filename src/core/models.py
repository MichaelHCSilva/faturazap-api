#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\models.py

"""Esquemas devolvidos pelo Gemini (usados como response_schema)."""
from typing import Optional

from pydantic import BaseModel


class ReceiptItem(BaseModel):
    description: str
    amount: float


class ReceiptData(BaseModel):
    """Dados de um cupom fiscal (NFC-e), vindo do texto da SEFAZ ou de uma foto."""
    store_name: Optional[str]
    cnpj: Optional[str]
    purchase_date: Optional[str]
    access_key: Optional[str]
    city: Optional[str]
    street: Optional[str]
    number: Optional[str]
    total_amount: Optional[float]
    items: list[ReceiptItem]


class StatementItem(BaseModel):
    purchase_date: Optional[str]
    description: Optional[str]
    city: Optional[str]
    street: Optional[str]
    number: Optional[str]
    amount: Optional[float]
    installment: Optional[str]


class StatementData(BaseModel):
    """Dados de uma fatura de cartão ou boleto em PDF."""
    card_name: Optional[str]
    due_date: Optional[str]
    total_amount: Optional[float]
    barcode: Optional[str]
    pix_payload: Optional[str]
    items: list[StatementItem]