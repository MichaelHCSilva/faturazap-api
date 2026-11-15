#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\drafts.py

"""Documentos lidos que ainda aguardam confirmação. Ficam só em memória, nunca no banco.

Cada pessoa tem uma fila: o primeiro rascunho é o que está em conversa.
Se o servidor reiniciar, os rascunhos não confirmados se perdem (é só enviar de novo).
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from src import config
from src.core.repository import NewStatement

# Estados da conversa
REVIEW = "review"        # mostrou o documento lido: "tudo meu" ou "dividir"?
ITEM = "item"            # perguntando quem participou de um item
CONFIRM = "confirm"      # mostrou a tabela final: gravar ou corrigir?
PICK_ITEM = "pick_item"  # escolhendo qual item corrigir


@dataclass
class Draft:
    statement: NewStatement
    state: str = REVIEW
    index: int = 0                                   # item atual (estado ITEM)
    selection: list[int] = field(default_factory=list)  # pessoas marcadas no item atual
    assignments: dict[int, list[int]] = field(default_factory=dict)  # item -> pessoas
    editing: bool = False                            # corrigindo um item já atribuído
    created_at: float = field(default_factory=time.time)


_lock = threading.Lock()
_queues: dict[int, list[Draft]] = {}


def _purge(owner_id: int) -> None:
    """Remove rascunhos expirados da fila (chamar com o lock já adquirido)."""
    now = time.time()
    queue = _queues.get(owner_id, [])
    _queues[owner_id] = [d for d in queue if now - d.created_at < config.DRAFT_TTL_SECONDS]


def add(owner_id: int, statement: NewStatement) -> Draft:
    draft = Draft(statement=statement)
    with _lock:
        _purge(owner_id)
        _queues.setdefault(owner_id, []).append(draft)
    return draft


def current(owner_id: int) -> Optional[Draft]:
    with _lock:
        _purge(owner_id)
        queue = _queues.get(owner_id)
        return queue[0] if queue else None


def count(owner_id: int) -> int:
    with _lock:
        _purge(owner_id)
        return len(_queues.get(owner_id, []))


def discard_current(owner_id: int) -> None:
    with _lock:
        queue = _queues.get(owner_id)
        if queue:
            queue.pop(0)


def has_identifier(identifier: Optional[str]) -> bool:
    """True se algum rascunho (de qualquer pessoa) já tem esse documento em andamento."""
    if not identifier:
        return False
    with _lock:
        return any(d.statement.identifier == identifier for q in _queues.values() for d in q)