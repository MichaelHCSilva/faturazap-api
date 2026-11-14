#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\api.py
"""API Flask do FaturaZap: webhook do WhatsApp, resumo financeiro e simulador web."""
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from src import config
from src.core import reporter
from src.core.database import init_db
from src.core.formatting import format_brl
from src.services import ingestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES

init_db()

IMAGE_FAILURE_MESSAGE = (
    "⚠️ Ops! Não consegui ler os dados dessa foto (talvez esteja apagada ou amassada). "
    "Quanto foi o valor gasto nessa compra?"
)


# --- Helpers -----------------------------------------------------------------------

def _reply(status: str, message: str, http_status: int = 200):
    return jsonify({"status": status, "response_message": message}), http_status


def _field(name: str):
    """Lê um campo de form-data ou de JSON."""
    value = request.form.get(name)
    if value is None:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            value = payload.get(name)
    return value


def _read_pdf_input():
    """PDF vindo como upload ('file') ou como nome de arquivo dentro de data/uploads."""
    upload = request.files.get("file")
    if upload:
        return upload.read()
    filename = _field("content")
    if filename:
        path = config.UPLOAD_DIR / Path(filename).name  # .name impede sair da pasta de uploads
        if path.is_file():
            return path.read_bytes()
    return None


# --- Handlers por tipo de mensagem ---------------------------------------------------

def _handle_pdf():
    pdf_bytes = _read_pdf_input()
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return _reply("error", "❌ Envie um arquivo PDF válido.", 400)

    result = ingestion.process_pdf(pdf_bytes)
    if result.status == "success":
        return _reply(
            "success",
            f"✅ Fatura **{result.store_name}** processada com sucesso!\n"
            f"💰 Valor Total: {format_brl(result.total_amount)}",
        )
    if result.status == "duplicate":
        return _reply("warning", "ℹ️ Essa fatura já foi processada antes.")
    return _reply(
        "failed",
        "⚠️ Não consegui ler essa fatura. Verifique se o PDF não está protegido por senha ou corrompido.",
        422,
    )


def _handle_qrcode():
    url = (_field("content") or "").strip()
    if not url:
        return _reply("error", "❌ Link do QR Code não fornecido.", 400)

    result = ingestion.process_qrcode(url)
    if result.status == "success":
        return _reply("success", "✅ Cupom fiscal processado e salvo com sucesso!")
    if result.status == "duplicate":
        return _reply("warning", "ℹ️ Esse cupom já foi processado antes.")
    return _reply(
        "warning",
        "⚠️ Site da SEFAZ instável. Cupom salvo na fila de reprocessamento automático.",
    )


def _handle_image():
    upload = request.files.get("image")
    if upload is None:
        return _reply("error", "❌ Nenhuma imagem foi enviada.", 400)

    mime_type = upload.mimetype if (upload.mimetype or "").startswith("image/") else "image/jpeg"
    result = ingestion.process_image(upload.read(), mime_type)
    if result.status == "success":
        return _reply(
            "success",
            f"✅ Nota de **{result.store_name or 'Estabelecimento'}** processada com sucesso via IA!\n"
            f"💰 Valor Total: {format_brl(result.total_amount)}\n"
            f"*(Dados salvos no sistema com sucesso!)*",
        )
    if result.status == "duplicate":
        return _reply("warning", "ℹ️ Esse cupom já foi processado antes.")
    return _reply("failed", IMAGE_FAILURE_MESSAGE)


HANDLERS = {"pdf": _handle_pdf, "qrcode": _handle_qrcode, "image": _handle_image}


# --- Rotas ---------------------------------------------------------------------------

@app.get("/")
def chat_ui():
    """Simulador visual de chat para testes no navegador."""
    return render_template("index.html")


@app.post("/webhook/whatsapp")
def whatsapp_webhook():
    message_type = _field("type")
    if not message_type:
        return _reply("error", "❌ Tipo de mensagem não informado.", 400)

    handler = HANDLERS.get(message_type)
    if handler is None:
        return _reply("error", "❌ Tipo de mensagem não suportado pelo sistema.", 400)

    try:
        return handler()
    except Exception:
        logger.exception("Erro inesperado no webhook (type=%s)", message_type)
        return _reply("error", "❌ Erro interno ao processar a mensagem.", 500)


@app.get("/webhook/summary")
def financial_summary():
    return _reply("success", reporter.get_financial_summary())


@app.post("/webhook/reprocess")
def reprocess_failed():
    """Reprocessa os links de QR Code que estão na fila de falhas."""
    summary = ingestion.reprocess_failed_qrcodes()
    return _reply(
        "success",
        f"🔄 Reprocessamento: {summary['success']} salvo(s), "
        f"{summary['duplicate']} duplicado(s), {summary['failed']} ainda com falha.",
    )


@app.errorhandler(413)
def file_too_large(_error):
    return _reply("error", "❌ Arquivo grande demais.", 413)


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )