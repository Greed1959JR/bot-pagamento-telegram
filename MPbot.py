import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, Response
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

USUARIO_ADMIN = "greedjr"
SENHA_ADMIN = "camisa10JR"

DB_FILE = "assinantes.json"
TEMP_PREFS = "pagamentos_temp.json"

app = Flask(__name__)
sdk = mercadopago.SDK(ACCESS_TOKEN)

ASSINATURA_VALOR = 19.90
DIAS_ASSINATURA = 30
PLANOS = {
    "mensal": {"dias": 30, "preco": 19.90},
    "trimestral": {"dias": 90, "preco": 52.90}
}

# === Utilitários ===
def carregar_dados():
    if not os.path.exists(DB_FILE): return {}
    with open(DB_FILE) as f: return json.load(f)

def salvar_dados(dados):
    with open(DB_FILE, 'w') as f: json.dump(dados, f, indent=4)

def salvar_temp_pagamento(preference_id, telegram_id, plano):
    if os.path.exists(TEMP_PREFS):
        with open(TEMP_PREFS) as f: dados = json.load(f)
    else: dados = {}
    dados[preference_id] = {"telegram_id": telegram_id, "plano": plano}
    with open(TEMP_PREFS, 'w') as f: json.dump(dados, f)

def carregar_temp_pagamento(preference_id):
    if not os.path.exists(TEMP_PREFS): return None
    with open(TEMP_PREFS) as f: dados = json.load(f)
    return dados.get(preference_id)

@app.route("/", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), BOT)

    if update.message:
        chat_id = update.message.chat.id
        user_id = update.message.from_user.id
        texto = update.message.text

        if texto == "/start":
            keyboard = [
                [telegram.InlineKeyboardButton("💰 Pagar Assinatura", callback_data="pagar")],
                [telegram.InlineKeyboardButton("📦 Ver Planos", callback_data="planos")],
                [telegram.InlineKeyboardButton("❓ Ajuda", callback_data="ajuda")],
            ]
            BOT.send_message(chat_id=chat_id, text="Bem-vindo! Escolha uma opção:", reply_markup=telegram.InlineKeyboardMarkup(keyboard))

        elif texto == "/status":
            dados = carregar_dados()
            info = dados.get(str(user_id))
            if info:
                venc = datetime.strptime(info["vencimento"], "%Y-%m-%d")
                dias = (venc - datetime.now()).days
                BOT.send_message(chat_id=chat_id, text=f"✅ Sua assinatura está ativa. Vence em {dias} dia(s), em {info['vencimento']}.")
            else:
                BOT.send_message(chat_id=chat_id, text="❌ Você não possui uma assinatura ativa.")

    elif update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat.id

        BOT.answer_callback_query(callback_query_id=query.id)

        if query.data == "ajuda":
            BOT.send_message(chat_id=chat_id, text="ℹ️ Escolha uma opção:\n- 💰 *Pagar Assinatura*: ativar acesso ao grupo.\n- 📦 *Ver Planos*: veja preços disponíveis.\n\n❓ Em caso de dúvidas, envie um email para: overgeared1959@gmail.com", parse_mode=telegram.constants.ParseMode.MARKDOWN)

        elif query.data == "planos":
            texto = "📦 *Planos disponíveis:*\n\n"
            for nome, plano in PLANOS.items():
                texto += f"✅ Plano {nome.capitalize()}: R${plano['preco']} por {plano['dias']} dias\n"
            BOT.send_message(chat_id=chat_id, text=texto, parse_mode=telegram.constants.ParseMode.MARKDOWN)

        elif query.data == "pagar":
            keyboard = []
            for nome, plano in PLANOS.items():
                keyboard.append([telegram.InlineKeyboardButton(f"{nome.capitalize()} - R${plano['preco']}", callback_data=f"comprar_{nome}")])
            BOT.send_message(chat_id=chat_id, text="Escolha o plano desejado:", reply_markup=telegram.InlineKeyboardMarkup(keyboard))

        elif query.data.startswith("comprar_"):
            plano = query.data.replace("comprar_", "")
            if plano not in PLANOS:
                BOT.send_message(chat_id=chat_id, text="Plano inválido.")
                return "ok"
            valor = PLANOS[plano]['preco']
            preference_data = {
                "items": [{"title": f"Assinatura {plano}", "quantity": 1, "currency_id": "BRL", "unit_price": valor}],
                "back_urls": {"success": "https://t.me/seu_bot"},
                "auto_return": "approved",
                "notification_url": WEBHOOK_URL + "/notificacao"
            }
            preference = sdk.preference().create(preference_data)
            checkout_url = preference["response"]["init_point"]
            preference_id = preference["response"]["id"]
            salvar_temp_pagamento(preference_id, user_id, plano)

            BOT.send_message(chat_id=chat_id, text="💳 Pague com Mercado Pago:")
            BOT.send_message(chat_id=chat_id, text=checkout_url)

    return "ok"

# === Processamento do Pagamento ===
def processar_pagamento(payment_id):
    payment = sdk.payment().get(payment_id)
    status = payment['response'].get('status')
    preference_id = payment['response'].get('preference_id')

    if status == 'approved':
        temp_info = carregar_temp_pagamento(preference_id)
        if not temp_info: return
        telegram_id = temp_info['telegram_id']
        plano = temp_info['plano']
        dias = PLANOS[plano]['dias']

        dados = carregar_dados()
        hoje = datetime.now()
        vencimento = (hoje + timedelta(days=dias)).strftime('%Y-%m-%d')

        dados[str(telegram_id)] = {"pagamento": hoje.strftime('%Y-%m-%d'), "vencimento": vencimento, "status": "ativo"}
        salvar_dados(dados)

        BOT.send_message(chat_id=telegram_id, text="✅ Pagamento aprovado! Você foi liberado no grupo.")
        BOT.send_message(chat_id=telegram_id, text=f"☚ Acesse o grupo: {GRUPO_LINK}")

# === Webhook de Notificação Mercado Pago ===
@app.route('/notificacao', methods=['POST'])
def notificacao():
    data = request.get_json()
    if data and "type" in data and data["type"] == "payment":
        payment_id = data.get("data", {}).get("id")
        if payment_id:
            Thread(target=processar_pagamento, args=(payment_id,)).start()
    return Response(status=200)

# === Painel Admin com edição ===
@app.route("/admin", methods=["GET"])
def painel():
    auth = request.authorization
    if not auth or auth.username != USUARIO_ADMIN or auth.password != SENHA_ADMIN:
        return Response("Acesso negado", 401, {"WWW-Authenticate": 'Basic realm="Login"'})

    dados = carregar_dados()
    html = """
    <html><body>
    <h2>Assinantes</h2>
    <table border='1'><tr><th>ID</th><th>Vencimento</th><th>Status</th><th>Ação</th></tr>
    """
    for uid, info in dados.items():
        html += f"<tr><td>{uid}</td><td>{info['vencimento']}</td><td>{info['status']}</td>"
        html += f"<td><a href='/remover/{uid}'>Remover</a> | "
        html += f"<a href='/alterar/{uid}/7'>+7 dias</a> | <a href='/alterar/{uid}/-7'>-7 dias</a></td></tr>"
    html += "</table></body></html>"
    return html

@app.route("/remover/<uid>", methods=["GET"])
def remover(uid):
    dados = carregar_dados()
    if uid in dados:
        del dados[uid]
        salvar_dados(dados)
        try:
            BOT.kick_chat_member(chat_id=GROUP_ID, user_id=int(uid))
        except Exception as e:
            print(f"Erro ao remover do grupo: {e}")
    return redirect(url_for('painel'))

@app.route("/alterar/<uid>/<int:dias>", methods=["GET"])
def alterar(uid, dias):
    dados = carregar_dados()
    if uid in dados:
        vencimento = datetime.strptime(dados[uid]['vencimento'], "%Y-%m-%d")
        novo_venc = vencimento + timedelta(days=dias)
        dados[uid]['vencimento'] = novo_venc.strftime("%Y-%m-%d")
        salvar_dados(dados)
    return redirect(url_for('painel'))

# === Tarefa de Verificação de Vencimento ===
def verificar_vencimentos():
    while True:
        dados = carregar_dados()
        hoje = datetime.now().strftime("%Y-%m-%d")
        for uid, info in list(dados.items()):
            if info['vencimento'] < hoje:
                try:
                    BOT.send_message(chat_id=int(uid), text="⏰ Sua assinatura expirou. Renovar para continuar no grupo.")
                    BOT.kick_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                except Exception as e:
                    print(f"Erro ao remover por expiração: {e}")
                del dados[uid]
        salvar_dados(dados)
        time.sleep(3600)

Thread(target=verificar_vencimentos, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
