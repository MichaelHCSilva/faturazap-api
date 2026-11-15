#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\database.py
"""Conexão e criação do esquema SQLite."""
import logging
import sqlite3
from contextlib import contextmanager

from src import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    phone TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- Só entram aqui documentos já confirmados pelo usuário.
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    owner_id INTEGER,
    store_name TEXT,
    due_date TEXT,
    total_amount REAL,
    barcode TEXT,
    qrcode TEXT,
    identifier TEXT,
    FOREIGN KEY (card_id) REFERENCES cards (id),
    FOREIGN KEY (owner_id) REFERENCES people (id)
);

CREATE TABLE IF NOT EXISTS statement_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER NOT NULL,
    purchase_date TEXT NOT NULL,
    description TEXT NOT NULL,
    city TEXT,
    street TEXT,
    number TEXT,
    amount REAL NOT NULL,
    installment TEXT,
    FOREIGN KEY (statement_id) REFERENCES statements (id) ON DELETE CASCADE
);

-- Quanto de cada item pertence a cada pessoa (em centavos inteiros).
CREATE TABLE IF NOT EXISTS item_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    FOREIGN KEY (item_id) REFERENCES statement_items (id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people (id),
    UNIQUE (item_id, person_id)
);

CREATE TABLE IF NOT EXISTS failed_qrcodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qrcode_url TEXT NOT NULL UNIQUE,
    owner_id INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES people (id)
);
"""

# Colunas adicionadas depois da primeira versão: aplicadas em bancos já existentes.
MIGRATIONS = (
    ("statements", "store_name", "TEXT"),
    ("statements", "identifier", "TEXT"),
    ("statements", "owner_id", "INTEGER REFERENCES people (id)"),
    ("failed_qrcodes", "owner_id", "INTEGER REFERENCES people (id)"),
)

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_statements_card_id ON statements (card_id);
CREATE INDEX IF NOT EXISTS idx_statements_owner ON statements (owner_id);
CREATE INDEX IF NOT EXISTS idx_items_statement_id ON statement_items (statement_id);
CREATE INDEX IF NOT EXISTS idx_shares_person ON item_shares (person_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_statements_identifier
    ON statements (identifier) WHERE identifier IS NOT NULL;
"""


@contextmanager
def get_connection():
    """Abre uma conexão com FKs ativas; faz commit no sucesso e rollback em erro."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    """Cria diretórios, tabelas, migrações e índices (idempotente)."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            _ensure_column(conn, table, column, ddl)
        conn.executescript(INDEXES)
    logger.info("Banco de dados pronto em %s", config.DB_PATH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()