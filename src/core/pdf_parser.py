#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\pdf_parser.py
import pdfplumber
import ollama
import sqlite3
import os
import json

DB_PATH = os.path.join("data", "faturazap.db")

def extract_pdf_text(file_path):
    # Extrai todo o texto bruto do PDF página por página
    full_text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    return full_text

def parse_and_save_statement(file_path):
    # 1. Pega o texto bruto do PDF da fatura
    raw_text = extract_pdf_text(file_path)
    
    # 2. Pergunta para o Ollama estruturar os dados no formato exato das tabelas
    prompt = f"""
    Analise o texto desta fatura de cartão de crédito e extraia os dados em formato JSON puro, contendo estritamente estas chaves:
    - "card_name" (nome do banco ou cartão, ex: Banco do Brasil, Carrefour, Senff)
    - "due_date" (data de vencimento)
    - "total_amount" (valor total da fatura como float)
    - "barcode" (código de barras ou linha digitável, se houver)
    - "qrcode" (payload pix, se houver)
    - "items" (uma lista de objetos contendo:
        - "purchase_date" (data da compra, obrigatório)
        - "description" (descrição ou nome da loja, obrigatório)
        - "city" (cidade do estabelecimento, se houver)
        - "street" (rua ou endereço, se houver)
        - "number" (número do endereço, se houver)
        - "amount" (valor da compra como float, obrigatório)
        - "installment" (parcela, ex: 1/1, ou null se não houver)
    )

    TEXTO DA FATURA:
    {raw_text}
    """

    response = ollama.chat(model='llama3', messages=[{
        'role': 'user',
        'content': prompt
    }])

    # 3. Limpa e converte a resposta da IA para um dicionário Python (JSON)
    ai_content = response['message']['content']
    
    if "```json" in ai_content:
        ai_content = ai_content.split("```json")[1].split("```")[0].strip()
    elif "```" in ai_content:
        ai_content = ai_content.split("```")[1].split("```")[0].strip()

    data = json.loads(ai_content)

    # 4. Salva os dados extraídos no banco SQLite respeitando as restrições e relações
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Garante que o nome do cartão não venha vazio
    card_name = data.get("card_name", "Desconhecido")
    cursor.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (card_name,))
    cursor.execute("SELECT id FROM cards WHERE name = ?", (card_name,))
    card_id = cursor.fetchone()[0]

    # Insere o cabeçalho da fatura na tabela 'statements'
    cursor.execute('''
        INSERT INTO statements (card_id, due_date, total_amount, barcode, qrcode)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        card_id,
        data.get("due_date"),
        data.get("total_amount"),
        data.get("barcode"),
        data.get("qrcode")
    ))
    statement_id = cursor.lastrowid

    # Insere cada compra detalhada na tabela 'statement_items' com segurança contra nulos em campos NOT NULL
    for item in data.get("items", []):
        purchase_date = item.get("purchase_date") or "00/00/0000"
        description = item.get("description") or "Sem descrição"
        amount = item.get("amount") or 0.0

        cursor.execute('''
            INSERT INTO statement_items (statement_id, purchase_date, description, city, street, number, amount, installment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            statement_id,
            purchase_date,
            description,
            item.get("city"),
            item.get("street"),
            item.get("number"),
            amount,
            item.get("installment")
        ))

    conn.commit()
    conn.close()
    
    print(f"✅ Fatura do cartão '{card_name}' processada e salva no banco com sucesso!")

if __name__ == "__main__":
    # Teste apontando para o arquivo da sua fatura
    # parse_and_save_statement("caminho/para/sua/fatura.pdf")
    pass