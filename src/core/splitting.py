#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\splitting.py

"""Contas da divisão (puras: sem banco, sem IA). Tudo em centavos inteiros."""
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: float) -> int:
    """Converte reais em centavos inteiros, arredondando metade para cima."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def split_cents(total_cents: int, person_ids: list[int], offset: int = 0) -> dict[int, int]:
    """Divide um valor entre as pessoas sem perder nem criar nenhum centavo.

    Os centavos que sobram são distribuídos um a um; o `offset` (ex.: posição do item)
    gira quem recebe primeiro, para a mesma pessoa não ficar sempre com os extras.
    """
    ids = sorted(set(person_ids))
    if not ids:
        raise ValueError("É preciso ao menos uma pessoa para dividir o valor.")
    base, remainder = divmod(total_cents, len(ids))
    shares = {pid: base for pid in ids}
    for k in range(remainder):
        shares[ids[(offset + k) % len(ids)]] += 1
    return shares


def build_shares(
    amounts: list[float], assignments: dict[int, list[int]], default_person: int
) -> list[tuple[int, int, int]]:
    """Gera (posição do item, pessoa, centavos) para todos os itens.

    Item sem atribuição fica inteiro com `default_person`.
    """
    shares = []
    for index, amount in enumerate(amounts):
        people = assignments.get(index) or [default_person]
        parts = split_cents(to_cents(amount), people, offset=index)
        shares.extend((index, person_id, cents) for person_id, cents in parts.items())
    return shares