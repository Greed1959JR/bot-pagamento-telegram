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
TEMP_PREFS = "pagamentos_temp.json"

app = Flask(__name__)
sdk = mercadopago.SDK(ACCESS_TOKEN)

ASSINATURA_VALOR = 10.00

# === Utilitários de Banco de Dados ===

def carregar_dados():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def salvar_dados(dados):
    with open(DB_FILE, 'w') as f:
        json.dump(dados, f, indent=4)

def salvar_temp_pagamento(preference_id, telegram_id):
    if os.path.exists(TEMP_PREFS):
        with open(TEMP_PREFS, 'r') as f:
            dados = json.load(f)
    else:
        dados = {}
    dados[preference_id] = telegram_id
    with open(TEMP_PREFS, 'w') as f:
        json.dump(dados, f)

def carregar_temp_pagamento(preference_id):
    if not os.path.exists(TEMP_PREFS):
        return None
    with open(TEMP_PREFS, 'r') as f:
        dados = json.load(f)
    return dados.get(preference_id)

# === Rota Principal (Telegram Bot) ===

@app.route("/", methods=["GET", "POST", "HEAD"])
def webhook():
    if request.method in ["GET", "HEAD"]:
        return "Bot de pagamento está ativo."

    update = telegram.Update.de_json(request.get_json(force=True), BOT)

    if update.message:
        chat_id = update.message.chat.id
        user_id = update.message.from_user.id
        texto = update.message.text

        if texto == "/start":
            BOT.send_message(
                chat_id=chat_id,
                text="Bem-vindo ao Bot de Apostas! Clique no botão abaixo para pagar sua assinatura.",
                reply_markup=telegram.InlineKeyboardMarkup([
                    [telegram.InlineKeyboardButton("\ud83d\udcb0 Pagar", callback_data="pagar")]
                ])
            )

        elif texto == "/status":
            dados = carregar_dados()
            info = dados.get(str(user_id))
            if info:
                venc = datetime.strptime(info["vencimento"], "%Y-%m-%d")
                dias = (venc - datetime.now()).days
                BOT.send_message(chat_id=chat_id, text=f"\u2705 Sua assinatura está ativa. Vence em {dias} dia(s), em {info['vencimento']}.")
            else:
                BOT.send_message(chat_id=chat_id, text="\u274c Você não possui uma assinatura ativa.")

    elif update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat.id

        if query.data == "pagar":
            url_base = os.getenv("WEBHOOK_URL")
            if not url_base.endswith("/notificacao"):
                url_base += "/notificacao"

            preference_data = {
                "items": [
                    {
                        "title": "Assinatura mensal do grupo",
                        "quantity": 1,
                        "currency_id": "BRL",
                        "unit_price": ASSINATURA_VALOR
                    }
                ],
                "back_urls": {
                    "success": "https://t.me/seu_bot",
                    "failure": "https://t.me/seu_bot",
                    "pending": "https://t.me/seu_bot"
                },
                "auto_return": "approved",
                "notification_url": url_base
            }

            preference = sdk.preference().create(preference_data)
            checkout_url = preference["response"]["init_point"]
            preference_id = preference["response"]["id"]

            salvar_temp_pagamento(preference_id, user_id)

            BOT.send_message(chat_id=chat_id, text="\ud83d\udcb3 Clique no link abaixo para pagar com Mercado Pago:")
            BOT.send_message(chat_id=chat_id, text=checkout_url)
            BOT.send_message(chat_id=chat_id, text="\ud83d\udca1 Após o pagamento, aguarde a confirmação automática aqui mesmo.")

    return "ok"

# === Processamento de Pagamento ===

def processar_pagamento(payment_id):
    print("\ud83d\udd04 Processando pagamento:", payment_id)
    payment_info = sdk.payment().get(payment_id)

    status = payment_info["response"]["status"]
    preference_id = payment_info["response"].get("order", {}).get("id") or payment_info["response"].get("preference_id")
    telegram_id = carregar_temp_pagamento(preference_id)

    print("\ud83d\udce6 Status:", status, " | Preference ID:", preference_id, " | Telegram ID:", telegram_id)

    if status == "approved" and telegram_id:
        dados = carregar_dados()
        hoje = datetime.now().strftime("%Y-%m-%d")
        vencimento = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        dados[str(telegram_id)] = {
            "pagamento": hoje,
            "vencimento": vencimento,
            "status": "ativo"
        }
        salvar_dados(dados)

        BOT.send_message(chat_id=telegram_id, text="\u2705 Pagamento aprovado! Você foi liberado no grupo.")
        BOT.send_message(chat_id=telegram_id, text=f"\u261b Acesse o grupo: {GRUPO_LINK}")

# === Rota de Notificação Mercado Pago ===

@app.route("/notificacao", methods=["POST"])
def notificacao():
    data = request.json
    print("\ud83d\udd14 Notificação recebida:", data)

    if not data:
        return "ignorado"

    if data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        processar_pagamento(payment_id)

    elif data.get("type") == "merchant_order":
        order_id = data.get("data", {}).get("id")
        print("\ud83d\udce6 Notificação de merchant_order:", order_id)

        order_info = sdk.merchant_order().get(order_id)
        payments = order_info["response"].get("payments", [])

        for payment in payments:
            if payment["status"] == "approved":
                payment_id = payment["id"]
                processar_pagamento(payment_id)

    return "ok"

# === Verificação Diária de Vencimentos ===

def verificar_vencimentos():
    while True:
        time.sleep(86400)
        dados = carregar_dados()
        hoje = datetime.now().strftime("%Y-%m-%d")

        for uid, info in list(dados.items()):
            if info["status"] == "ativo":
                dias_restantes = (datetime.strptime(info["vencimento"], "%Y-%m-%d") - datetime.now()).days
                if dias_restantes == 3:
                    try:
                        BOT.send_message(chat_id=int(uid), text="\u23f3 Sua assinatura vence em 3 dias. Renove para continuar no grupo sem interrupções.")
                    except Exception as e:
                        print(f"Erro ao avisar {uid}: {e}")
                if info["vencimento"] < hoje:
                    try:
                        BOT.send_message(chat_id=int(uid), text="\u26a0\ufe0f Sua assinatura expirou. Você será removido do grupo.")
                        BOT.ban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                        BOT.unban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                    except Exception as e:
                        print(f"Erro ao remover {uid}: {e}")
                    dados[uid]["status"] = "inativo"

        salvar_dados(dados)

# === Iniciar Verificação em Thread ===

verificacao_thread = Thread(target=verificar_vencimentos)
verificacao_thread.daemon = True
verificacao_thread.start()

# === Executar Localmente (Render usa Gunicorn) ===

if __name__ == '__main__':
    print("Rodando localmente. Em produção, use gunicorn.")
