from flask import Flask, request, jsonify
import requests
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Variáveis de ambiente
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Garante que o ID do grupo tenha o prefixo "-100"
if TELEGRAM_GROUP_ID and not TELEGRAM_GROUP_ID.startswith("-100"):
    TELEGRAM_GROUP_ID = f"-100{TELEGRAM_GROUP_ID}"

@app.route("/")
def home():
    return "Bot de pagamento está rodando!"

@app.route("/pagar", methods=["POST"])
def pagar():
    data = request.get_json()
    telegram_id = data.get("telegram_id")

    if not telegram_id:
        return jsonify({"error": "telegram_id é obrigatório"}), 400

    url = "https://api.mercadopago.com/checkout/preferences"
    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "items": [{
            "title": "Acesso ao grupo",
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": 1.00
        }],
        "metadata": {
            "telegram_id": telegram_id
        },
        "notification_url": WEBHOOK_URL,
        "back_urls": {
            "success": "https://t.me/seubot",
            "failure": "https://t.me/seubot"
        },
        "auto_return": "approved"
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 201:
        return jsonify(response.json()["init_point"])
    else:
        return jsonify({"error": "Erro ao criar pagamento"}), 500

@app.route("/notificacao", methods=["POST"])
def notificacao():
    data = request.get_json()
    logging.info(f"📬 Notificação recebida: {data}")

    payment_id = data.get("data", {}).get("id")

    if not payment_id:
        return jsonify({"error": "ID do pagamento não encontrado"}), 400

    # Consulta pagamento
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}"
    }
    r = requests.get(url, headers=headers)
    pagamento = r.json()

    status = pagamento.get("status")
    telegram_id = pagamento.get("metadata", {}).get("telegram_id")

    logging.info(f"🔍 Processando pagamento {payment_id} | Status: {status} | Telegram ID: {telegram_id}")

    if status == "approved" and telegram_id:
        add_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/inviteChatMember"
        payload = {
            "chat_id": TELEGRAM_GROUP_ID,
            "user_id": telegram_id
        }
        res = requests.post(add_url, json=payload)
        if res.status_code == 200:
            logging.info(f"✅ Usuário {telegram_id} adicionado ao grupo com sucesso!")
        else:
            logging.error(f"❌ Erro ao adicionar {telegram_id} ao grupo: {res.text}")
    else:
        logging.warning("Pagamento não aprovado ou telegram_id ausente.")

    return jsonify({"status": "ok"}), 200
