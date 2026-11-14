#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\formatting.py
"""Funções de formatação compartilhadas."""

def format_brl(value: float) -> str:
    """Formata um número como moeda brasileira: 1234.5 -> 'R$ 1.234,50'."""
    text = f"{value:,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")