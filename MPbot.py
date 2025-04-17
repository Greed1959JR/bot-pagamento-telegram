import os
import json
from datetime import datetime, timedelta
from flask import Flask, request
import telegram
import mercadopago
from dotenv import load_dotenv
from threading import Thread
import time

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
BOT = telegram.Bot(token=TELEGRAM_TOKEN)
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID"))
GRUPO_LINK = os.getenv("GRUPO_LINK")

DB_FILE = "assinantes.json"

app = Flask(__name__)
sdk = mercadopago.SDK(ACCESS_TOKEN)

ASSINATURA_VALOR = 1.00

# === Banco de Dados ===

def carregar_dados():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def salvar_dados(dados):
    with open(DB_FILE, 'w') as f:
        json.dump(dados, f, indent=4)

# === Criação de Preferência com Telegram ID no Metadata ===

def criar_preferencia_pagamento(telegram_id):
    url_base = os.getenv("WEBHOOK_URL")
    if not url_base.endswith("/notificacao"):
        url_base += "/notificacao"

    preference_data = {
        "items": [
            {
                "title": "Assinatura do grupo",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": ASSINATURA_VALOR
            }
        ],
        "metadata": {
            "telegram_id": telegram_id
        },
        "notification_url": url_base,
        "back_urls": {
            "success": "https://t.me/seu_bot",
            "failure": "https://t.me/seu_bot",
            "pending": "https://t.me/seu_bot"
        },
        "auto_return": "approved"
    }

    preference_response = sdk.preference().create(preference_data)
    return preference_response["response"]["init_point"]

# === Webhook Telegram ===

@app.route("/", methods=["GET", "POST", "HEAD"])
def webhook():
    if request.method in ["GET", "HEAD"]:
        return "Bot ativo."

    update = telegram.Update.de_json(request.get_json(force=True), BOT)

    if update.message:
        chat_id = update.message.chat.id
        user_id = update.message.from_user.id
        texto = update.message.text

        if texto == "/start":
            BOT.send_message(
                chat_id=chat_id,
                text="Bem-vindo! Clique abaixo para pagar sua assinatura.",
                reply_markup=telegram.InlineKeyboardMarkup([
                    [telegram.InlineKeyboardButton("💰 Pagar", callback_data="pagar")]
                ])
            )

    elif update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat.id

        if query.data == "pagar":
            checkout_url = criar_preferencia_pagamento(user_id)
            BOT.send_message(chat_id=chat_id, text="💳 Clique no link abaixo para pagar com Mercado Pago:")
            BOT.send_message(chat_id=chat_id, text=checkout_url)
            BOT.send_message(chat_id=chat_id, text="💡 Após o pagamento, aguarde a confirmação aqui mesmo.")

    return "ok"

# === Processamento do Pagamento ===

def adicionar_ao_grupo(telegram_id):
    try:
        BOT.unban_chat_member(chat_id=GROUP_ID, user_id=int(telegram_id))
        BOT.send_message(chat_id=telegram_id, text="✅ Pagamento aprovado! Você foi liberado no grupo.")
        BOT.send_message(chat_id=telegram_id, text=f"☛ Acesse o grupo: {GRUPO_LINK}")
    except Exception as e:
        print(f"Erro ao adicionar {telegram_id}: {e}")

def salvar_assinatura(telegram_id, dias):
    dados = carregar_dados()
    hoje = datetime.now()
    vencimento = hoje + timedelta(days=dias)
    dados[str(telegram_id)] = {
        "pagamento": hoje.strftime("%Y-%m-%d"),
        "vencimento": vencimento.strftime("%Y-%m-%d"),
        "status": "ativo"
    }
    salvar_dados(dados)

def processar_pagamento(payment_id):
    print("Processando pagamento:", payment_id)
    payment_info = sdk.payment().get(payment_id)
    payment = payment_info["response"]

    status = payment.get("status")
    telegram_id = payment.get("metadata", {}).get("telegram_id")
    print("Status:", status, "| Telegram ID:", telegram_id)

    if status == "approved" and telegram_id:
        adicionar_ao_grupo(telegram_id)
        salvar_assinatura(telegram_id, dias=1)

# === Rota de Notificação ===

@app.route("/notificacao", methods=["POST"])
def notificacao():
    data = request.json
    print("Notificação recebida:", data)

    if data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        if payment_id:
            processar_pagamento(payment_id)

    return "ok"

# === Monitoramento de Assinaturas ===

def verificar_vencimentos():
    while True:
        time.sleep(30)
        dados = carregar_dados()
        hoje = datetime.now()

        for uid, info in list(dados.items()):
            if info["status"] == "ativo":
                venc = datetime.strptime(info["vencimento"], "%Y-%m-%d")
                dias_restantes = (venc - hoje).days

                if dias_restantes == 1:
                    try:
                        BOT.send_message(chat_id=int(uid), text="⏳ Sua assinatura vence amanhã. Renove para continuar no grupo.")
                    except Exception as e:
                        print(f"Erro ao notificar {uid}: {e}")

                if venc < hoje:
                    try:
                        BOT.send_message(chat_id=int(uid), text="❌ Sua assinatura expirou. Você será removido do grupo.")
                        BOT.ban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                        BOT.unban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                        dados[uid]["status"] = "inativo"
                    except Exception as e:
                        print(f"Erro ao remover {uid}: {e}")

        salvar_dados(dados)

verificacao_thread = Thread(target=verificar_vencimentos)
verificacao_thread.daemon = True
verificacao_thread.start()

if __name__ == '__main__':
    print("Bot rodando localmente. Em produção use gunicorn.")
