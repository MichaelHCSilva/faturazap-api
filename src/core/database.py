#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\database.py
import sqlite3
import os

DB_PATH = os.path.join("data", "faturazap.db")

def init_db():
    # Garante que o diretório de dados existe localmente
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Tabela de cartões para armazenar origens dinâmicas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    # Tabela de cabeçalho de extratos para faturas ou comprovantes por QR code
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS statements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER NOT NULL,
            due_date TEXT,
            total_amount REAL,
            barcode TEXT,
            qrcode TEXT,
            FOREIGN KEY (card_id) REFERENCES cards (id)
        )
    ''')

    # Tabela de itens detalhados do extrato para registros individuais de compras
    cursor.execute('''
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
            FOREIGN KEY (statement_id) REFERENCES statements (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS failed_qrcodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qrcode_url TEXT NOT NULL UNIQUE,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')




    conn.commit()
    conn.close()
    print("✅ Tabelas 'cards', 'statements' e 'statement_items' criadas com sucesso no banco!")

if __name__ == "__main__":
    init_db()