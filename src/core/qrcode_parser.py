#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\qrcode_parser.py
import sqlite3
import os
import requests
from bs4 import BeautifulSoup
from src.services.gemini_service import (
    extract_receipt_data_with_gemini,
    extract_receipt_from_image_with_gemini
)

DB_PATH = os.path.join("data", "faturazap.db")

def parse_and_save_qrcode(qrcode_url):
    """
    Acessa o link do QR Code da SEFAZ, utiliza o serviço isolado do Gemini para extração
    e persiste os dados de forma relacional no SQLite.
    """
    print(f"🔄 Acessando o link do cupom fiscal: {qrcode_url}")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(qrcode_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            raise Exception(f"HTTP Status code: {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.extract()
            
        raw_page_text = soup.get_text(separator="\n", strip=True)

        data = extract_receipt_data_with_gemini(raw_page_text)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        payment_method = "Cupom Fiscal / SEFAZ"
        cursor.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (payment_method,))
        cursor.execute("SELECT id FROM cards WHERE name = ?", (payment_method,))
        card_id = cursor.fetchone()[0]

        store_name = data.get("store_name", "Estabelecimento Desconhecido")
        purchase_date = data.get("purchase_date", "00/00/0000")
        total_amount = float(data.get("total_amount", 0.0))

        cursor.execute('''
            INSERT INTO statements (card_id, due_date, total_amount, qrcode)
            VALUES (?, ?, ?, ?)
        ''', (card_id, purchase_date, total_amount, qrcode_url))
        statement_id = cursor.lastrowid

        city = data.get("city")
        street = data.get("street")
        number = data.get("number")

        for item in data.get("items", []):
            description = item.get("description") or "Item sem descrição"
            amount = float(item.get("amount") or 0.0)

            cursor.execute('''
                INSERT INTO statement_items (statement_id, purchase_date, description, city, street, number, amount, installment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                statement_id,
                purchase_date,
                description,
                city,
                street,
                str(number) if number is not None else None,
                amount,
                None
            ))

        conn.commit()
        conn.close()
        
        print(f"✅ Cupom fiscal de '{store_name}' processado via Gemini Service e salvo com sucesso!")
        return True

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Erro ao processar o QR Code da SEFAZ: {error_msg}")
        
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO failed_qrcodes (qrcode_url, error_message)
                VALUES (?, ?)
            ''', (qrcode_url, error_msg))
            conn.commit()
            conn.close()
            print("⚠️ Link armazenado na fila de pendências.")
        except Exception as db_error:
            print(f"❌ Erro ao salvar na fila de falhas: {db_error}")

        return False


def parse_and_save_whatsapp_image(image_bytes):
    """
    Processa a foto enviada diretamente pelo WhatsApp (fallback quando o QR code físico falha).
    Usa a visão do Gemini para extrair os dados da imagem e persiste no SQLite.
    """
    print("🔄 Processando imagem do cupom via Visão do Gemini (WhatsApp)...")
    
    try:
        data = extract_receipt_from_image_with_gemini(image_bytes)

        total_amount = float(data.get("total_amount", 0.0))
        if total_amount <= 0:
            raise ValueError("O valor total extraído da imagem é inválido ou zerado.")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        payment_method = "Cupom Fiscal / WhatsApp"
        cursor.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (payment_method,))
        cursor.execute("SELECT id FROM cards WHERE name = ?", (payment_method,))
        card_id = cursor.fetchone()[0]

        store_name = data.get("store_name", "Estabelecimento Desconhecido")
        purchase_date = data.get("purchase_date", "00/00/0000")
        access_key = data.get("access_key", "FOTO_DIRETA")

        cursor.execute('''
            INSERT INTO statements (card_id, due_date, total_amount, qrcode)
            VALUES (?, ?, ?, ?)
        ''', (card_id, purchase_date, total_amount, access_key))
        statement_id = cursor.lastrowid

        city = data.get("city")
        street = data.get("street")
        number = data.get("number")

        for item in data.get("items", []):
            description = item.get("description") or "Item sem descrição"
            amount = float(item.get("amount") or 0.0)

            cursor.execute('''
                INSERT INTO statement_items (statement_id, purchase_date, description, city, street, number, amount, installment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                statement_id,
                purchase_date,
                description,
                city,
                street,
                str(number) if number is not None else None,
                amount,
                None
            ))

        conn.commit()
        conn.close()
        
        print(f"✅ Cupom de '{store_name}' processado via Foto do WhatsApp e salvo com sucesso!")
        return {"status": "success", "data": data}

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Erro ao processar a foto do cupom: {error_msg}")
        return {
            "status": "failed", 
            "message": "⚠️ Ops! Não consegui ler os dados dessa foto (talvez esteja apagada ou amassada). Quanto foi o valor gasto nessa compra?"
        }