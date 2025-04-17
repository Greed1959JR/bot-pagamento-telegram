import os
import time
import threading
from flask import Flask, request
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

assinaturas = {}

@app.route('/')
def home():
    return 'Bot de Pagamento está ativo!'

@app.route('/start', methods=['POST'])
def start():
    data = request.json
    telegram_id = data["message"]["from"]["id"]
    link_pagamento = gerar_link_pagamento(telegram_id)
    enviar_mensagem(telegram_id, f"Para acessar o grupo, realize o pagamento: {link_pagamento}")
    return "OK", 200

def gerar_link_pagamento(telegram_id):
    url = "https://api.mercadopago.com/checkout/preferences"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    payload = {
        "items": [{"title": "Assinatura Grupo", "quantity": 1, "currency_id": "BRL", "unit_price": 1.00}],
        "notification_url": os.getenv("WEBHOOK_URL"),
        "metadata": {"telegram_id": telegram_id}
    }
    response = requests.post(url, json=payload, headers=headers)
    return response.json()["init_point"]

@app.route('/notificacao', methods=['POST'])
def notificacao():
    data = request.json
    if data.get("type") == "payment":
        payment_id = data["data"]["id"]
        verificar_pagamento(payment_id)
    return "OK", 200

def verificar_pagamento(payment_id):
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    pagamento = response.json()

    if pagamento["status"] == "approved":
        telegram_id = str(pagamento["metadata"]["telegram_id"])
        adicionar_ao_grupo(telegram_id)
        enviar_mensagem(telegram_id, "Pagamento confirmado! Você foi adicionado ao grupo.")
        expiracao = datetime.now() + timedelta(days=1)  # ✅ 1 dia de acesso para testes
        assinaturas[telegram_id] = expiracao

def adicionar_ao_grupo(telegram_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/unbanChatMember"
    payload = {"chat_id": TELEGRAM_GROUP_ID, "user_id": telegram_id}
    requests.post(url, json=payload)

def enviar_mensagem(chat_id, texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    requests.post(url, json=payload)

def verificar_assinaturas():
    while True:
        agora = datetime.now()
        expirados = []
        for telegram_id, validade in list(assinaturas.items()):
            restante = validade - agora

            if restante.total_seconds() < 3600 and restante.total_seconds() > 0:  # ✅ Avisa com 1 hora restante
                enviar_mensagem(telegram_id, "Sua assinatura vai expirar em 1 hora! Faça um novo pagamento para continuar.")
            elif restante.total_seconds() <= 0:
                enviar_mensagem(telegram_id, "Sua assinatura expirou. Você será removido do grupo.")
                remover_do_grupo(telegram_id)
                expirados.append(telegram_id)

        for telegram_id in expirados:
            del assinaturas[telegram_id]

        time.sleep(60)  # Verifica a cada 1 minuto

def remover_do_grupo(telegram_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/kickChatMember"
    payload = {"chat_id": TELEGRAM_GROUP_ID, "user_id": telegram_id}
    requests.post(url, json=payload)

# Iniciar verificação em paralelo
threading.Thread(target=verificar_assinaturas, daemon=True).start()

if __name__ == '__main__':
    app.run(port=5000)
