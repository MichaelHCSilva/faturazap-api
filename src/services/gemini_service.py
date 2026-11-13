#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\services\gemini_service.py
import os
import json
from google import genai
from google.genai import types

def extract_receipt_data_with_gemini(raw_page_text):
    """
    Envia o texto bruto do cupom fiscal para a API do Gemini com a ferramenta de busca web ativada (v1beta),
    utilizando o CNPJ e os dados do estabelecimento para validar e buscar o número oficial correto na internet.
    """
    client = genai.Client(http_options={'api_version': 'v1beta'})

    prompt = f"""
    Analise o texto extraído da página de uma Nota Fiscal de Consumidor Eletrônica (NFC-e) de qualquer estado do Brasil.
    Identifique e extraia os dados estritamente em formato JSON puro contendo estas chaves exatas:
    - "store_name" (nome do estabelecimento, string)
    - "purchase_date" (data da compra no formato DD/MM/AAAA, string)
    - "city" (cidade do estabelecimento, string ou null)
    - "street" (rua ou logradouro do estabelecimento, string ou null)
    - "number" (número do endereço, string. REGRA CRÍTICA DE VALIDAÇÃO: 
      1. Se o cupom fiscal original trouxer um número válido (diferente de "0", vazio ou "S/N"), utilize-o.
      2. Se o número vier como "0", vazio ou ausente, você DEVE procurar na internet utilizando o **CNPJ do estabelecimento** presente no texto da nota fiscal ou o nome da loja + rua + cidade.
      3. Dê preferência absoluta ao número oficial de cadastro fiscal/CNPJ do local encontrado na web (ex: se o cadastro do CNPJ na receita/web indica 3050, utilize 3050). O campo "number" deve conter estritamente o número oficial apurado).
    - "total_amount" (valor total da nota fiscal como float)
    - "items" (lista de objetos contendo:
        - "description" (nome limpo e descrição pura do produto, sem repetir o nome do mercado, string)
        - "amount" (valor total do item como float)
    )

    TEXTO DA NOTA FISCAL:
    {raw_page_text}
    """

    try:
        response_ai = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{'google_search': {}}]
            )
        )
        
        ai_content = response_ai.text.strip()
        
        if "```json" in ai_content:
            ai_content = ai_content.split("```json")[1].split("```")[0].strip()
        elif "```" in ai_content:
            ai_content = ai_content.split("```")[1].split("```")[0].strip()

        return json.loads(ai_content)
    
    except Exception as e:
        raise Exception(f"Erro na comunicação com a API do Gemini: {str(e)}")


def extract_receipt_from_image_with_gemini(image_bytes):
    """
    Analisa a imagem binária do cupom enviada pelo WhatsApp usando o Gemini Vision.
    Extrai dados visuais (nome, data, chave de acesso, endereço, itens e valores)
    diretamente da foto quando o QR Code físico ou o link da SEFAZ falharem.
    """
    client = genai.Client(http_options={'api_version': 'v1beta'})

    prompt = """
    Analise esta foto de um cupom fiscal brasileiro (NFC-e).
    Identifique e extraia os dados estritamente em formato JSON puro contendo estas chaves exatas:
    - "store_name" (nome do estabelecimento, string)
    - "purchase_date" (data da compra no formato DD/MM/AAAA, string)
    - "access_key" (a Chave de Acesso de 44 dígitos impressa ao lado do QR code, string ou null)
    - "city" (cidade do estabelecimento, string ou null)
    - "street" (rua ou logradouro do estabelecimento, string ou null)
    - "number" (número do endereço, string. Se for "0" ou ausente, busque na web usando o CNPJ da nota)
    - "total_amount" (valor total da nota fiscal como float)
    - "items" (lista de objetos contendo:
        - "description" (nome limpo e descrição pura do produto, string)
        - "amount" (valor total do item como float)
    )
    """

    try:
        response_ai = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/jpeg",
                ),
                prompt
            ],
            config=types.GenerateContentConfig(
                tools=[{'google_search': {}}]
            )
        )
        
        ai_content = response_ai.text.strip()
        
        if "```json" in ai_content:
            ai_content = ai_content.split("```json")[1].split("```")[0].strip()
        elif "```" in ai_content:
            ai_content = ai_content.split("```")[1].split("```")[0].strip()

        return json.loads(ai_content)
    
    except Exception as e:
        raise Exception(f"Erro na visão do Gemini ao processar a imagem do cupom: {str(e)}")