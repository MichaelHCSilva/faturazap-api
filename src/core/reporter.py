#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\reporter.py

"""Resumo financeiro por cartão/origem."""
import logging
import sqlite3

from src.core import repository
from src.core.formatting import format_brl

logger = logging.getLogger(__name__)


def get_financial_summary() -> str:
    try:
        rows = repository.get_totals_by_card()
    except sqlite3.Error:
        logger.exception("Erro ao consultar o resumo financeiro")
        return "❌ Erro ao gerar o relatório financeiro."

    if not rows:
        return "📊 Você ainda não possui faturas ou cupons processados no FaturaZap."

    lines = ["📊 *Resumo Financeiro FaturaZap*", ""]
    for row in rows:
        lines.append(f"💳 *{row['card_name']}* ({row['statements_count']} documento(s))")
        lines.append(f"   Total: {format_brl(row['total_spent'])}")
        lines.append("")

    general_total = sum(row["total_spent"] for row in rows)
    lines.append(f"💰 *Gasto Total Acumulado:* {format_brl(general_total)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(get_financial_summary())