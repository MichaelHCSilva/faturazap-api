#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\repository.py
"""Acesso a dados: todo SQL do projeto fica aqui."""
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from src.core.database import get_connection


class DuplicateStatementError(Exception):
    """Já existe um extrato com o mesmo identifier (chave de acesso ou hash do PDF)."""


class DuplicatePersonError(Exception):
    """Já existe uma pessoa com esse nome ou telefone."""


@dataclass
class NewItem:
    purchase_date: str
    description: str
    amount: float
    city: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    installment: Optional[str] = None


@dataclass
class NewStatement:
    card_name: str
    total_amount: float
    owner_id: Optional[int] = None
    due_date: Optional[str] = None
    store_name: Optional[str] = None
    barcode: Optional[str] = None
    qrcode: Optional[str] = None
    identifier: Optional[str] = None
    items: list[NewItem] = field(default_factory=list)


# --- Pessoas -----------------------------------------------------------------------

def create_person(name: str, phone: Optional[str] = None) -> int:
    with get_connection() as conn:
        try:
            cursor = conn.execute("INSERT INTO people (name, phone) VALUES (?, ?)", (name, phone))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicatePersonError(name) from exc
            raise
    return cursor.lastrowid


def list_people() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT id, name, phone FROM people ORDER BY id").fetchall()


def get_person(person_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT id, name, phone FROM people WHERE id = ?", (person_id,)).fetchone()


def get_person_by_phone(phone: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT id, name, phone FROM people WHERE phone = ?", (phone,)).fetchone()


# --- Extratos ----------------------------------------------------------------------

def _get_or_create_card(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM cards WHERE name = ?", (name,)).fetchone()["id"]


def identifier_exists(identifier: Optional[str]) -> bool:
    """True se um documento com esse identifier já foi gravado."""
    if not identifier:
        return False
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM statements WHERE identifier = ? LIMIT 1", (identifier,)).fetchone()
    return row is not None


def save_statement(statement: NewStatement, shares: tuple | list = ()) -> int:
    """Grava extrato, itens e divisão numa única transação. Retorna o id do extrato.

    `shares` é uma lista de (posição do item, id da pessoa, centavos).
    """
    with get_connection() as conn:
        card_id = _get_or_create_card(conn, statement.card_name)
        try:
            cursor = conn.execute(
                """
                INSERT INTO statements
                    (card_id, owner_id, store_name, due_date, total_amount, barcode, qrcode, identifier)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    statement.owner_id,
                    statement.store_name,
                    statement.due_date,
                    statement.total_amount,
                    statement.barcode,
                    statement.qrcode,
                    statement.identifier,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateStatementError(statement.identifier) from exc
            raise

        statement_id = cursor.lastrowid
        item_ids = []
        for item in statement.items:
            item_cursor = conn.execute(
                """
                INSERT INTO statement_items
                    (statement_id, purchase_date, description, city, street, number, amount, installment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    statement_id,
                    item.purchase_date,
                    item.description,
                    item.city,
                    item.street,
                    item.number,
                    item.amount,
                    item.installment,
                ),
            )
            item_ids.append(item_cursor.lastrowid)

        conn.executemany(
            "INSERT INTO item_shares (item_id, person_id, amount_cents) VALUES (?, ?, ?)",
            [(item_ids[index], person_id, cents) for index, person_id, cents in shares],
        )
    return statement_id


# --- Consultas por pessoa ----------------------------------------------------------

def get_person_totals(person_id: int) -> list[sqlite3.Row]:
    """Quanto a pessoa gastou por origem (cartão, cupom...)."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.name AS origin,
                   SUM(sh.amount_cents) AS total_cents,
                   COUNT(DISTINCT s.id) AS statements_count
            FROM item_shares sh
            JOIN statement_items i ON i.id = sh.item_id
            JOIN statements s ON s.id = i.statement_id
            JOIN cards c ON c.id = s.card_id
            WHERE sh.person_id = ?
            GROUP BY c.id
            ORDER BY total_cents DESC
            """,
            (person_id,),
        ).fetchall()


def get_person_entries(person_id: int, limit: int = 20) -> list[sqlite3.Row]:
    """Últimos lançamentos da pessoa (a parte dela em cada item)."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT s.id AS statement_id,
                   COALESCE(s.store_name, c.name) AS origin,
                   i.purchase_date, i.description, sh.amount_cents
            FROM item_shares sh
            JOIN statement_items i ON i.id = sh.item_id
            JOIN statements s ON s.id = i.statement_id
            JOIN cards c ON c.id = s.card_id
            WHERE sh.person_id = ?
            ORDER BY s.id DESC, i.id
            LIMIT ?
            """,
            (person_id, limit),
        ).fetchall()


# --- Fila de QR Codes que falharam -------------------------------------------------

def save_failed_qrcode(url: str, error_message: str, owner_id: Optional[int] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO failed_qrcodes (qrcode_url, error_message, owner_id) VALUES (?, ?, ?)
            ON CONFLICT(qrcode_url) DO UPDATE SET
                error_message = excluded.error_message,
                owner_id = COALESCE(failed_qrcodes.owner_id, excluded.owner_id)
            """,
            (url, error_message, owner_id),
        )


def list_failed_qrcodes() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT qrcode_url, owner_id FROM failed_qrcodes ORDER BY id").fetchall()


def delete_failed_qrcode(url: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM failed_qrcodes WHERE qrcode_url = ?", (url,))