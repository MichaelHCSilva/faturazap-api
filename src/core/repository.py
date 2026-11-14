#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\repository.py
"""Acesso a dados: todo SQL do projeto fica aqui."""
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from src.core.database import get_connection


class DuplicateStatementError(Exception):
    """Já existe um extrato com o mesmo identifier (chave de acesso ou hash do PDF)."""


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
    due_date: Optional[str] = None
    store_name: Optional[str] = None
    barcode: Optional[str] = None
    qrcode: Optional[str] = None
    identifier: Optional[str] = None
    items: list[NewItem] = field(default_factory=list)


def _get_or_create_card(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM cards WHERE name = ?", (name,)).fetchone()["id"]


def save_statement(statement: NewStatement) -> int:
    """Grava o extrato e seus itens numa única transação. Retorna o id do extrato."""
    with get_connection() as conn:
        card_id = _get_or_create_card(conn, statement.card_name)
        try:
            cursor = conn.execute(
                """
                INSERT INTO statements
                    (card_id, store_name, due_date, total_amount, barcode, qrcode, identifier)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
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
        conn.executemany(
            """
            INSERT INTO statement_items
                (statement_id, purchase_date, description, city, street, number, amount, installment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    statement_id,
                    item.purchase_date,
                    item.description,
                    item.city,
                    item.street,
                    item.number,
                    item.amount,
                    item.installment,
                )
                for item in statement.items
            ],
        )
    return statement_id


def get_totals_by_card() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.name AS card_name,
                   COALESCE(SUM(s.total_amount), 0) AS total_spent,
                   COUNT(s.id) AS statements_count
            FROM statements s
            JOIN cards c ON c.id = s.card_id
            GROUP BY c.id
            ORDER BY total_spent DESC
            """
        ).fetchall()


# --- Fila de QR Codes que falharam -------------------------------------------------

def save_failed_qrcode(url: str, error_message: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO failed_qrcodes (qrcode_url, error_message) VALUES (?, ?)
            ON CONFLICT(qrcode_url) DO UPDATE SET error_message = excluded.error_message
            """,
            (url, error_message),
        )


def list_failed_qrcodes() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT qrcode_url FROM failed_qrcodes ORDER BY id").fetchall()
    return [row["qrcode_url"] for row in rows]


def delete_failed_qrcode(url: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM failed_qrcodes WHERE qrcode_url = ?", (url,))