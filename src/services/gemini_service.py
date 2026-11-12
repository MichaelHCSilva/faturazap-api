#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\gemini_service.py

import os
import json
from google import genai

def extract_receipt_data_with_gemini(raw_page_text):
    """
    Envia o texto bruto do cupom fiscal para a API do Gemini e retorna os dados estruturados em JSON.
    """
    # Garante que pega a chave de ambiente configurada no WSL2
    client = genai.Client()

    prompt = f"""
    Analise o texto extraído da página de uma Nota Fiscal de Consumidor Eletrônica (NFC-e) de qualquer estado do Brasil.
    Identifique e extraia os dados estritamente em formato JSON puro contendo estas chaves exatas:
    - "store_name" (nome do estabelecimento, string)
    - "purchase_date" (data da compra no formato DD/MM/AAAA, string)
    - "city" (cidade do estabelecimento, string ou null)
    - "street" (rua ou logradouro do estabelecimento, string ou null)
    - "number" (número do endereço, string como "0", "123" ou "S/N", null se não houver)
    - "total_amount" (valor total da nota fiscal como float)
    - "items" (lista de objetos contendo:
        - "description" (nome e descrição do produto, string)
        - "amount" (valor total do item como float)
    )

    TEXTO DA NOTA FISCAL:
    {raw_page_text}
    """

    try:
        response_ai = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        ai_content = response_ai.text.strip()
        
        # Limpa blocos Markdown se houver
        if "```json" in ai_content:
            ai_content = ai_content.split("```json")[1].split("```")[0].strip()
        elif "```" in ai_content:
            ai_content = ai_content.split("```")[1].split("```")[0].strip()

        return json.loads(ai_content)
    
    except Exception as e:
        raise Exception(f"Erro na comunicação com a API do Gemini: {str(e)}")