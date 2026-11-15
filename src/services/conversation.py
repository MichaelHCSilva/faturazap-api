#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\conversation.py
"""Conversa guiada por cliques: mostra o documento lido, atribui cada item e só grava após confirmação.

Fluxo (o estado fica no rascunho, em memória):
    REVIEW  -> documento lido: "Tudo meu" ou "Dividir itens"
    ITEM    -> um item por vez: marca quem participou e segue
    CONFIRM -> tabela final com o responsável de cada item: "Gravar" ou "Corrigir"
    gravado -> só aqui os dados vão para o banco

As mensagens do usuário chegam como comandos curtos (valor dos botões), por exemplo
"mode:split", "toggle:2", "next", "save".
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.core import repository
from src.core.formatting import format_brl, format_cents
from src.core.repository import DuplicateStatementError, NewStatement
from src.core.splitting import build_shares
from src.services import drafts
from src.services.drafts import CONFIRM, ITEM, PICK_ITEM, REVIEW, Draft

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Não há nada em andamento. Envie um cupom (link do QR Code ou foto) ou uma fatura em PDF. "
    "Para ver seus gastos, use *Resumo* ou *Lançamentos*."
)
_RESUME = {"continuar", "pendencias", "pendências"}
_CANCEL = {"cancel", "cancelar"}


@dataclass
class Chip:
    label: str
    value: str


@dataclass
class Reply:
    text: str
    table: Optional[dict] = None
    chips: list[Chip] = field(default_factory=list)


# --- Helpers -----------------------------------------------------------------------

def _people() -> dict[int, str]:
    return {row["id"]: row["name"] for row in repository.list_people()}


def _origin(statement: NewStatement) -> str:
    return statement.store_name or statement.card_name


def _items_table(statement: NewStatement) -> dict:
    rows = [
        [str(i + 1), item.description, format_brl(item.amount)]
        for i, item in enumerate(statement.items)
    ]
    return {
        "columns": ["#", "Item", "Valor"],
        "rows": rows,
        "footer": ["", "Total", format_brl(statement.total_amount)],
    }


def _sum_warning(statement: NewStatement) -> str:
    items_sum = round(sum(item.amount for item in statement.items), 2)
    if abs(items_sum - statement.total_amount) > 0.01:
        return (
            f"\n⚠️ A soma dos itens ({format_brl(items_sum)}) difere do total do documento "
            f"({format_brl(statement.total_amount)})."
        )
    return ""


def _final_table(draft: Draft, owner_id: int) -> tuple[dict, list[tuple[int, int, int]]]:
    """Tabela final com o responsável de cada item e a parte de cada pessoa."""
    statement = draft.statement
    people = _people()
    shares = build_shares([i.amount for i in statement.items], draft.assignments, owner_id)

    involved = sorted({person_id for _, person_id, _ in shares})
    by_item: dict[int, dict[int, int]] = {}
    for index, person_id, cents in shares:
        by_item.setdefault(index, {})[person_id] = cents

    rows = []
    for index, item in enumerate(statement.items):
        parts = by_item.get(index, {})
        names = [people.get(pid, f"#{pid}") for pid in sorted(parts)]
        who = names[0] if len(names) == 1 else "Dividido: " + ", ".join(names)
        rows.append(
            [str(index + 1), item.description, format_brl(item.amount), who]
            + [format_cents(parts[pid]) if pid in parts else "" for pid in involved]
        )

    totals = {pid: sum(c for _, p, c in shares if p == pid) for pid in involved}
    table = {
        "columns": ["#", "Item", "Valor", "Responsável"] + [people.get(pid, f"#{pid}") for pid in involved],
        "rows": rows,
        "footer": ["", "Total", format_brl(statement.total_amount), ""]
        + [format_cents(totals[pid]) for pid in involved],
    }
    return table, shares


# --- Perguntas (o que o bot mostra em cada estado) -------------------------------------

def _review_prompt(owner_id: int, draft: Draft) -> Reply:
    statement = draft.statement
    owner = repository.get_person(owner_id)
    return Reply(
        f"{owner['name']}, li *{_origin(statement)}* ({statement.due_date}): "
        f"{format_brl(statement.total_amount)}. Confere se está certo:{_sum_warning(statement)}",
        _items_table(statement),
        [
            Chip("✅ Tudo meu", "mode:mine"),
            Chip("✂️ Dividir itens", "mode:split"),
            Chip("ℹ️ Detalhes", "details"),
            Chip("🗑️ Cancelar", "cancel"),
        ],
    )


def _item_prompt(owner_id: int, draft: Draft) -> Reply:
    items = draft.statement.items
    item = items[draft.index]
    chips = [
        Chip(("✓ " if pid in draft.selection else "") + name, f"toggle:{pid}")
        for pid, name in _people().items()
    ]
    chips.append(Chip("▶ Próximo", "next"))
    chips.append(Chip("Só eu", "solo"))
    if not draft.editing and draft.index < len(items) - 1:
        chips.append(Chip("Resto: igual a este", "rest"))
    chips.append(Chip("ℹ️ Detalhes", "details"))
    chips.append(Chip("🗑️ Cancelar", "cancel"))
    return Reply(
        f"Item {draft.index + 1}/{len(items)}: *{item.description}* ({format_brl(item.amount)}). "
        f"Quem participou? Toque para marcar e depois em *Próximo*.",
        None,
        chips,
    )


def _confirm_prompt(owner_id: int, draft: Draft) -> Reply:
    table, _ = _final_table(draft, owner_id)
    return Reply(
        f"Confere o resultado de *{_origin(draft.statement)}*. Posso gravar?",
        table,
        [
            Chip("✅ Gravar", "save"),
            Chip("✏️ Corrigir item", "fix"),
            Chip("🗑️ Cancelar", "cancel"),
        ],
    )


def _pick_prompt(draft: Draft) -> Reply:
    chips = [
        Chip(f"{i + 1}. {item.description[:16]}", f"fixitem:{i}")
        for i, item in enumerate(draft.statement.items)
    ]
    chips.append(Chip("↩ Voltar", "back"))
    return Reply("Qual item você quer corrigir?", None, chips)


def _prompt(owner_id: int, draft: Draft) -> Reply:
    if draft.state == REVIEW:
        return _review_prompt(owner_id, draft)
    if draft.state == ITEM:
        return _item_prompt(owner_id, draft)
    if draft.state == CONFIRM:
        return _confirm_prompt(owner_id, draft)
    return _pick_prompt(draft)


def _with_note(reply: Reply, note: str) -> Reply:
    reply.text = f"{note}\n\n{reply.text}"
    return reply


def _after(owner_id: int, message: str) -> Reply:
    """Mostra `message` e, se houver outro documento na fila, já começa a conversa dele."""
    following = drafts.current(owner_id)
    if following is None:
        return Reply(message)
    reply = _prompt(owner_id, following)
    reply.text = f"{message}\n\nPróximo documento da fila:\n{reply.text}"
    return reply


def _details(owner_id: int, draft: Draft) -> Reply:
    """Dados para a pessoa se lembrar da compra: loja, endereço, data e ticket."""
    statement = draft.statement
    first = statement.items[0]
    lines = [f"ℹ️ *{_origin(statement)}*", f"Data: {statement.due_date}"]
    address = ", ".join(p for p in (first.street, first.number) if p)
    if address or first.city:
        lines.append("Endereço: " + " — ".join(p for p in (address, first.city) if p))
    if statement.qrcode:
        lines.append(f"Ticket: {statement.qrcode}")
    if statement.identifier and not statement.identifier.startswith("pdf:"):
        lines.append(f"Chave de acesso: {statement.identifier}")
    return _with_note(_prompt(owner_id, draft), "\n".join(lines))


# --- Entrada de documentos ---------------------------------------------------------

def add_document(owner_id: int, statement: NewStatement) -> Reply:
    """Registra um documento lido (ainda sem gravar) e começa a conversa, ou o enfileira."""
    if drafts.has_identifier(statement.identifier):
        return Reply("ℹ️ Esse documento já está em andamento.")

    draft = drafts.add(owner_id, statement)
    if drafts.count(owner_id) > 1:
        return Reply(
            f"✅ Li *{_origin(statement)}*: {format_brl(statement.total_amount)}. "
            f"Já está na fila; pergunto assim que terminarmos o documento atual."
        )
    return _prompt(owner_id, draft)


# --- Respostas do usuário ----------------------------------------------------------

def _enter_item(owner_id: int, draft: Draft, index: int) -> None:
    draft.state = ITEM
    draft.index = index
    draft.selection = list(draft.assignments.get(index, [owner_id]))


def _advance(owner_id: int, draft: Draft) -> Reply:
    """Vai para o próximo item, ou para a tabela final quando acabam (ou ao corrigir um item)."""
    last = draft.index >= len(draft.statement.items) - 1
    if draft.editing or last:
        draft.editing = False
        draft.state = CONFIRM
    else:
        _enter_item(owner_id, draft, draft.index + 1)
    return _prompt(owner_id, draft)


def _on_review(owner_id: int, draft: Draft, cmd: str) -> Optional[Reply]:
    if cmd == "mode:mine":
        draft.assignments = {i: [owner_id] for i in range(len(draft.statement.items))}
        draft.state = CONFIRM
        return _prompt(owner_id, draft)
    if cmd == "mode:split":
        draft.assignments = {}
        _enter_item(owner_id, draft, 0)
        return _prompt(owner_id, draft)
    return None


def _on_item(owner_id: int, draft: Draft, cmd: str) -> Optional[Reply]:
    if cmd.startswith("toggle:"):
        try:
            person_id = int(cmd.split(":", 1)[1])
        except ValueError:
            return None
        if person_id not in _people():
            return None
        if person_id in draft.selection:
            draft.selection.remove(person_id)
        else:
            draft.selection.append(person_id)
        return _prompt(owner_id, draft)

    if cmd == "solo":
        draft.selection = [owner_id]
        cmd = "next"

    if cmd in ("next", "rest"):
        if not draft.selection:
            return _with_note(_prompt(owner_id, draft), "Marque ao menos uma pessoa.")
        people = sorted(draft.selection)
        if cmd == "rest" and not draft.editing:
            for index in range(draft.index, len(draft.statement.items)):
                draft.assignments[index] = people
            draft.state = CONFIRM
            return _prompt(owner_id, draft)
        draft.assignments[draft.index] = people
        return _advance(owner_id, draft)
    return None


def _on_confirm(owner_id: int, draft: Draft, cmd: str) -> Optional[Reply]:
    if cmd == "fix":
        draft.state = PICK_ITEM
        return _prompt(owner_id, draft)
    if cmd != "save":
        return None

    table, shares = _final_table(draft, owner_id)
    draft.statement.owner_id = owner_id
    try:
        repository.save_statement(draft.statement, shares)
    except DuplicateStatementError:
        drafts.discard_current(owner_id)
        return _after(owner_id, "ℹ️ Esse documento já foi processado antes.")

    drafts.discard_current(owner_id)
    parts = [f"• {name}: {cell}" for name, cell in zip(table["columns"][4:], table["footer"][4:])]
    return _after(owner_id, "✅ Gravado! Parte de cada um:\n" + "\n".join(parts))


def _on_pick(owner_id: int, draft: Draft, cmd: str) -> Optional[Reply]:
    if cmd == "back":
        draft.state = CONFIRM
        return _prompt(owner_id, draft)
    if cmd.startswith("fixitem:"):
        try:
            index = int(cmd.split(":", 1)[1])
        except ValueError:
            return None
        if not 0 <= index < len(draft.statement.items):
            return None
        draft.editing = True
        _enter_item(owner_id, draft, index)
        return _prompt(owner_id, draft)
    return None


_HANDLERS = {REVIEW: _on_review, ITEM: _on_item, CONFIRM: _on_confirm, PICK_ITEM: _on_pick}


def handle_message(owner_id: int, text: str) -> Reply:
    """Recebe o comando (valor de um botão ou texto digitado) e devolve o próximo passo."""
    draft = drafts.current(owner_id)
    if draft is None:
        return Reply(HELP_TEXT)

    cmd = text.strip().lower()
    if cmd in _RESUME:
        return _prompt(owner_id, draft)
    if cmd in _CANCEL:
        drafts.discard_current(owner_id)
        return _after(owner_id, "🗑️ Documento cancelado. Nada foi gravado.")
    if cmd == "details":
        return _details(owner_id, draft)

    reply = _HANDLERS[draft.state](owner_id, draft, cmd)
    if reply is None:
        return _with_note(_prompt(owner_id, draft), "Não entendi. Use os botões abaixo.")
    return reply