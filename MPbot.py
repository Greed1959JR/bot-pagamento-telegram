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

DB_FILE = "assinantes.json"

app = Flask(__name__)

sdk = mercadopago.SDK(ACCESS_TOKEN)
ASSINATURA_VALOR = 1.00

# Utilitários para banco de dados

def carregar_dados():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def salvar_dados(dados):
    with open(DB_FILE, 'w') as f:
        json.dump(dados, f, indent=4)

# Menu do bot
@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "Bot de pagamento está ativo."

    update = telegram.Update.de_json(request.get_json(force=True), BOT)
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id

    if update.message.text == "/start":
        BOT.send_message(
            chat_id=chat_id,
            text="Bem-vindo ao Bot de Apostas! Clique no botão abaixo para pagar sua assinatura.",
            reply_markup=telegram.ReplyKeyboardMarkup(
                [[telegram.KeyboardButton("\uD83D\uDCB0 Pagar")]],
                resize_keyboard=True
            )
        )

    elif update.message.text == "\uD83D\uDCB0 Pagar":
        payment_data = {
            "transaction_amount": ASSINATURA_VALOR,
            "description": "Assinatura mensal do grupo",
            "payment_method_id": "pix",
            "payer": {
                "email": f"{user_id}@fakeemail.com"
            },
            "notification_url": os.getenv("WEBHOOK_URL")
        }

        payment = sdk.payment().create(payment_data)
        pix_data = payment["response"]

        BOT.send_message(chat_id=chat_id, text=f"\uD83D\uDD17 Link para pagar via Mercado Pago:")
        BOT.send_message(chat_id=chat_id, text=pix_data['point_of_interaction']['transaction_data']['ticket_url'])
        BOT.send_message(chat_id=chat_id, text="\uD83D\uDCA1 Após o pagamento, aguarde a confirmação automática aqui mesmo.")

    return "ok"

# Notificação de pagamento
@app.route("/notificacao", methods=["POST"])
def notificacao():
    data = request.json

    if data and data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        payment_info = sdk.payment().get(payment_id)

        status = payment_info["response"]["status"]
        payer_email = payment_info["response"]["payer"]["email"]
        telegram_id = int(payer_email.split("@")[0])

        if status == "approved":
            dados = carregar_dados()
            hoje = datetime.now().strftime("%Y-%m-%d")
            vencimento = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

            dados[str(telegram_id)] = {
                "pagamento": hoje,
                "vencimento": vencimento,
                "status": "ativo"
            }
            salvar_dados(dados)

            BOT.send_message(chat_id=telegram_id, text="\u2705 Pagamento aprovado! Você foi liberado no grupo.")

    return "ok"

# Verificador diário de vencimentos

def verificar_vencimentos():
    while True:
        time.sleep(86400)  # Executa 1x por dia
        dados = carregar_dados()
        hoje = datetime.now().strftime("%Y-%m-%d")

        for uid, info in list(dados.items()):
            if info["status"] == "ativo" and info["vencimento"] < hoje:
                try:
                    BOT.send_message(chat_id=int(uid), text="\u26A0\uFE0F Sua assinatura expirou. Você será removido do grupo.")
                    BOT.ban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                    BOT.unban_chat_member(chat_id=GROUP_ID, user_id=int(uid))  # Permite voltar depois
                except Exception as e:
                    print(f"Erro ao remover {uid}: {e}")
                dados[uid]["status"] = "inativo"

        salvar_dados(dados)

# Início da thread de verificação
verificacao_thread = Thread(target=verificar_vencimentos)
verificacao_thread.daemon = True
verificacao_thread.start()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
