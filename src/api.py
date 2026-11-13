#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\api.py
import os
from flask import Flask, request, jsonify, render_template
from src.core.database import init_db
from src.core.pdf_parser import parse_and_save_statement
from src.core.qrcode_parser import parse_and_save_qrcode, parse_and_save_whatsapp_image
from src.core.reporter import get_financial_summary

app = Flask(__name__, template_folder="templates")

# Inicializa o banco de dados e as tabelas ao subir a aplicação
init_db()

@app.route("/")
def chat_ui():
    """
    Exibe o simulador visual de chat no navegador para testes práticos.
    """
    return render_template("index.html")

@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    # Verifica se a requisição veio via multipart/form-data (com arquivo de imagem) ou application/json
    message_type = request.form.get("type") or (request.json.get("type") if request.is_json else None)
    
    if not message_type:
        return jsonify({"status": "error", "message": "Tipo de mensagem não informado."}), 400

    try:
        # Fluxo 1: Processamento de PDF
        if message_type == "pdf":
            content = request.json.get("content") if request.is_json else request.form.get("content")
            if content and os.path.exists(content):
                parse_and_save_statement(content)
                return jsonify({
                    "status": "success", 
                    "response_message": "✅ Fatura em PDF processada e salva com sucesso!"
                })
            else:
                return jsonify({
                    "status": "error", 
                    "response_message": "❌ Arquivo PDF não encontrado no servidor."
                }), 404
                
        # Fluxo 2: Processamento de Link de QR Code
        elif message_type == "qrcode":
            content = request.json.get("content") if request.is_json else request.form.get("content")
            if not content:
                return jsonify({"status": "error", "response_message": "❌ Link do QR Code não fornecido."}), 400
                
            success = parse_and_save_qrcode(content)
            if success:
                return jsonify({
                    "status": "success", 
                    "response_message": "✅ Cupom fiscal processado e salvo com sucesso!"
                })
            else:
                return jsonify({
                    "status": "warning", 
                    "response_message": "⚠️ Site da SEFAZ instável. Cupom salvo na fila de reprocessamento automático."
                })

        # Fluxo 3: Processamento de Foto do Cupom (Visão do Gemini)
        elif message_type == "image":
            if 'image' not in request.files:
                return jsonify({"status": "error", "response_message": "❌ Nenhuma imagem foi enviada."}), 400
            
            image_file = request.files['image']
            image_bytes = image_file.read()

            result = parse_and_save_whatsapp_image(image_bytes)

            if result.get("status") == "success":
                data = result.get("data", {})
                store = data.get("store_name", "Estabelecimento")
                total = data.get("total_amount", 0.0)
                return jsonify({
                    "status": "success",
                    "response_message": f"✅ Nota de **{store}** processada com sucesso via IA!\n💰 Valor Total: R$ {total:.2f}\n*(Dados salvos no sistema com sucesso!)*"
                })
            else:
                return jsonify({
                    "status": "failed",
                    "response_message": result.get("message", "⚠️ Não foi possível ler o cupom.")
                })
        
        else:
            return jsonify({
                "status": "error", 
                "response_message": "❌ Tipo de mensagem não suportado pelo sistema."
            }), 400

    except Exception as e:
        return jsonify({"status": "error", "response_message": f"❌ Erro interno: {str(e)}"}), 500

@app.route("/webhook/summary", methods=["GET"])
def financial_summary():
    summary_text = get_financial_summary()
    return jsonify({
        "status": "success",
        "response_message": summary_text
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)