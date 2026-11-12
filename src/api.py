#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\api.py
import os
from flask import Flask, request, jsonify, render_template
from src.core.database import init_db
from src.core.pdf_parser import parse_and_save_statement
from src.core.qrcode_parser import parse_and_save_qrcode
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
    data = request.json
    
    if not data:
        return jsonify({"status": "error", "message": "Nenhum dado recebido."}), 400

    message_type = data.get("type")
    content = data.get("content")
    
    if not message_type or not content:
        return jsonify({"status": "error", "message": "Parâmetros 'type' e 'content' são obrigatórios."}), 400

    try:
        if message_type == "pdf":
            if os.path.exists(content):
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
                
        elif message_type == "qrcode":
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