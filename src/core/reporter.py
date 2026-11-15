#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\reporter.py

"""Resumo e lançamentos de cada pessoa."""
import logging
import sqlite3

from src.core import repository
from src.core.formatting import format_cents

logger = logging.getLogger(__name__)

_ERROR = "❌ Erro ao consultar seus gastos."


def get_financial_summary(person_id: int) -> str:
    """Quanto a pessoa gastou por origem, considerando só a parte dela em cada item."""
    try:
        person = repository.get_person(person_id)
        rows = repository.get_person_totals(person_id)
    except sqlite3.Error:
        logger.exception("Erro ao consultar o resumo financeiro")
        return _ERROR

    if person is None:
        return "❌ Pessoa não encontrada."
    if not rows:
        return f"📊 {person['name']}, você ainda não tem gastos confirmados no FaturaZap."

    lines = [f"📊 *Resumo de {person['name']}*", ""]
    for row in rows:
        lines.append(f"💳 *{row['origin']}* ({row['statements_count']} documento(s))")
        lines.append(f"   Total: {format_cents(row['total_cents'])}")
        lines.append("")

    lines.append(f"💰 *Seu gasto total:* {format_cents(sum(row['total_cents'] for row in rows))}")
    return "\n".join(lines)


def get_entries(person_id: int, limit: int = 20) -> str:
    """Últimos lançamentos da pessoa (a parte dela em cada item)."""
    try:
        person = repository.get_person(person_id)
        rows = repository.get_person_entries(person_id, limit)
    except sqlite3.Error:
        logger.exception("Erro ao consultar os lançamentos")
        return _ERROR

    if person is None:
        return "❌ Pessoa não encontrada."
    if not rows:
        return f"🧾 {person['name']}, você ainda não tem lançamentos confirmados."

    lines = [f"🧾 *Últimos lançamentos de {person['name']}*", ""]
    for row in rows:
        lines.append(
            f"{row['purchase_date']} · {row['origin']} · {row['description']}: "
            f"{format_cents(row['amount_cents'])}"
        )
    return "\n".join(lines)