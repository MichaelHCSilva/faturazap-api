#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\api.py
"""API Flask do FaturaZap: webhook do WhatsApp, conversa de divisão, resumos e simulador web."""
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from src import config
from src.core import reporter, repository
from src.core.database import init_db
from src.services import conversation, ingestion
from src.services.conversation import Reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES

init_db()

IMAGE_FAILURE_MESSAGE = (
    "⚠️ Ops! Não consegui ler os dados dessa foto (talvez esteja apagada ou amassada). "
    "Tente outra foto mais nítida ou envie o link do QR Code."
)


# --- Helpers -----------------------------------------------------------------------

def _reply(status: str, message: str, http_status: int = 200):
    return jsonify({"status": status, "response_message": message}), http_status


def _conversation_reply(reply: Reply):
    """Resposta da conversa: texto, tabela (opcional) e botões (opcionais)."""
    body = {"status": "success", "response_message": reply.text}
    if reply.table:
        body["table"] = reply.table
    if reply.chips:
        body["quick_replies"] = [{"label": chip.label, "value": chip.value} for chip in reply.chips]
    return jsonify(body), 200


def _field(name: str):
    """Lê um campo de form-data, da query string ou de JSON."""
    value = request.form.get(name)
    if value is None:
        value = request.args.get(name)
    if value is None:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            value = payload.get(name)
    return value


def _sender():
    """Pessoa que está falando: por person_id (simulador) ou por telefone (WhatsApp real)."""
    raw_id = _field("person_id")
    if raw_id not in (None, ""):
        try:
            return repository.get_person(int(raw_id))
        except (TypeError, ValueError):
            return None
    phone = _field("phone")
    if phone:
        return repository.get_person_by_phone(phone)
    return None


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

def _handle_text(sender):
    content = (_field("content") or "").strip()
    if not content:
        return _reply("error", "❌ Mensagem vazia.", 400)
    return _conversation_reply(conversation.handle_message(sender["id"], content))


def _handle_pdf(sender):
    pdf_bytes = _read_pdf_input()
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return _reply("error", "❌ Envie um arquivo PDF válido.", 400)

    result = ingestion.read_pdf(pdf_bytes)
    if result.status == "success":
        return _conversation_reply(conversation.add_document(sender["id"], result.statement))
    if result.status == "duplicate":
        return _reply("warning", "ℹ️ Essa fatura já foi processada antes.")
    return _reply(
        "failed",
        "⚠️ Não consegui ler essa fatura. Verifique se o PDF não está protegido por senha ou corrompido.",
        422,
    )


def _handle_qrcode(sender):
    url = (_field("content") or "").strip()
    if not url:
        return _reply("error", "❌ Link do QR Code não fornecido.", 400)

    result = ingestion.read_qrcode(url, sender["id"])
    if result.status == "success":
        return _conversation_reply(conversation.add_document(sender["id"], result.statement))
    if result.status == "duplicate":
        return _reply("warning", "ℹ️ Esse cupom já foi processado antes.")
    return _reply(
        "warning",
        "⚠️ Site da SEFAZ instável. Cupom salvo na fila de reprocessamento automático.",
    )


def _handle_image(sender):
    upload = request.files.get("image")
    if upload is None:
        return _reply("error", "❌ Nenhuma imagem foi enviada.", 400)

    mime_type = upload.mimetype if (upload.mimetype or "").startswith("image/") else "image/jpeg"
    result = ingestion.read_image(upload.read(), mime_type)
    if result.status == "success":
        return _conversation_reply(conversation.add_document(sender["id"], result.statement))
    if result.status == "duplicate":
        return _reply("warning", "ℹ️ Esse cupom já foi processado antes.")
    return _reply("failed", IMAGE_FAILURE_MESSAGE)


HANDLERS = {
    "text": _handle_text,
    "pdf": _handle_pdf,
    "qrcode": _handle_qrcode,
    "image": _handle_image,
}


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

    sender = _sender()
    if sender is None:
        return _reply("error", "❌ Pessoa não identificada. Cadastre-se e selecione quem está falando.", 400)

    try:
        return handler(sender)
    except Exception:
        logger.exception("Erro inesperado no webhook (type=%s)", message_type)
        return _reply("error", "❌ Erro interno ao processar a mensagem.", 500)


@app.get("/people")
def list_people():
    return jsonify([dict(row) for row in repository.list_people()])


@app.post("/people")
def create_person():
    name = (_field("name") or "").strip()
    phone = (_field("phone") or "").strip() or None
    if not name:
        return _reply("error", "❌ Informe o nome da pessoa.", 400)
    try:
        person_id = repository.create_person(name, phone)
    except repository.DuplicatePersonError:
        return _reply("error", "❌ Já existe uma pessoa com esse nome ou telefone.", 409)
    return jsonify({"id": person_id, "name": name, "phone": phone}), 201


@app.get("/webhook/summary")
def financial_summary():
    sender = _sender()
    if sender is None:
        return _reply("error", "❌ Pessoa não identificada.", 400)
    return _reply("success", reporter.get_financial_summary(sender["id"]))


@app.get("/webhook/entries")
def entries():
    sender = _sender()
    if sender is None:
        return _reply("error", "❌ Pessoa não identificada.", 400)
    return _reply("success", reporter.get_entries(sender["id"]))


@app.post("/webhook/reprocess")
def reprocess_failed():
    """Reprocessa os links da fila. Cada dono vê o documento ao digitar 'continuar'."""
    counts, ready = ingestion.reprocess_failed_qrcodes()
    for owner_id, statement in ready:
        conversation.add_document(owner_id, statement)
    return _reply(
        "success",
        f"🔄 Reprocessamento: {counts['success']} lido(s) (aguardando confirmação), "
        f"{counts['duplicate']} duplicado(s), {counts['failed']} ainda com falha, "
        f"{counts['skipped']} sem dono.",
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