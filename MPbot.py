import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, Response, redirect, url_for
import telegram
import mercadopago
from dotenv import load_dotenv
from threading import Thread, Lock
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
lock = Lock()

PLANOS = {
    "mensal": {"valor": 5.00, "dias": 0, "minutos": 10},
    "trimestral": {"valor": 52.90, "dias": 90}
}

USUARIO_ADMIN = "greedjr"
SENHA_ADMIN = "camisa10JR"

# === Utilitários de Banco de Dados ===

def carregar_dados():
    with lock:
        if not os.path.exists(DB_FILE):
            return {}
        with open(DB_FILE, 'r') as f:
            return json.load(f)

def salvar_dados(dados):
    with lock:
        with open(DB_FILE, 'w') as f:
            json.dump(dados, f, indent=4)

def salvar_temp_pagamento(preference_id, telegram_id, plano):
    with lock:
        if os.path.exists(TEMP_PREFS):
            with open(TEMP_PREFS, 'r') as f:
                dados = json.load(f)
        else:
            dados = {}
        dados[preference_id] = {"telegram_id": telegram_id, "plano": plano}
        with open(TEMP_PREFS, 'w') as f:
            json.dump(dados, f)

def carregar_temp_pagamento(preference_id):
    with lock:
        if not os.path.exists(TEMP_PREFS):
            return None
        with open(TEMP_PREFS, 'r') as f:
            dados = json.load(f)
        return dados.get(preference_id)
# === Rota para ver e gerenciar assinantes com autenticação ===

@app.route("/painel", methods=["GET", "POST"])
def painel():
    auth = request.authorization
    if not auth or auth.username != USUARIO_ADMIN or auth.password != SENHA_ADMIN:
        return Response("Acesso negado", 401, {"WWW-Authenticate": "Basic realm='Login Requerido'"})

    dados = carregar_dados()

    if request.method == "POST":
        uid_remover = request.form.get("remover")
        confirmar = request.form.get("confirmar_remover")

        if uid_remover and confirmar == uid_remover:
            if uid_remover in dados:
                try:
                    BOT.send_message(chat_id=int(uid_remover), text="❌ Sua assinatura foi encerrada manualmente pelo administrador.")
                    BOT.ban_chat_member(chat_id=GROUP_ID, user_id=int(uid_remover))
                    BOT.unban_chat_member(chat_id=GROUP_ID, user_id=int(uid_remover))
                except Exception as e:
                    print(f"Erro ao remover manualmente {uid_remover}: {e}")
                del dados[uid_remover]
                salvar_dados(dados)
            return redirect(url_for('painel'))

    filtro = request.args.get("filtro", "ativos")
    html = f"""
        <h2>Painel de Assinantes ({filtro}):</h2>
        <form method='get'>
            <select name='filtro' onchange='this.form.submit()'>
                <option value='ativos' {'selected' if filtro == 'ativos' else ''}>Ativos</option>
                <option value='inativos' {'selected' if filtro == 'inativos' else ''}>Inativos</option>
                <option value='todos' {'selected' if filtro == 'todos' else ''}>Todos</option>
            </select>
        </form>
        <form method='post' onsubmit="return confirm('Tem certeza que deseja remover este usuário?');">
        <ul>
    """
    for uid, info in dados.items():
        if filtro == "ativos" and info.get("status") != "ativo":
            continue
        if filtro == "inativos" and info.get("status") != "inativo":
            continue

        nome = info.get("nome", "Desconhecido")
        pagamento_fmt = datetime.strptime(info["pagamento"], "%Y-%m-%d").strftime("%d/%m/%Y")
        vencimento_fmt = datetime.strptime(info["vencimento"], "%Y-%m-%d").strftime("%d/%m/%Y")
        html += f"<li><b>{nome}</b> (ID: {uid}) — Pagamento: {pagamento_fmt} | Vencimento: {vencimento_fmt} | Status: {info['status']} <button name='remover' value='{uid}'>Remover</button><input type='hidden' name='confirmar_remover' value='{uid}'></li>"

    html += """
        </ul>
        </form>
    """
    return html

# === Webhook Telegram ===

@app.route("/", methods=["GET", "POST", "HEAD"])
def webhook():
    if request.method in ["GET", "HEAD"]:
        return "Bot de pagamento está ativo."

    update = telegram.Update.de_json(request.get_json(force=True), BOT)

    if update.message:
        chat_id = update.message.chat.id
        user_id = update.message.from_user.id
        texto = update.message.text.lower()

        if texto == "/start":
            BOT.send_message(
                chat_id=chat_id,
                text="Bem-vindo ao Bot de Apostas! Use o menu abaixo para navegar.",
                reply_markup=telegram.InlineKeyboardMarkup([
                    [
                        telegram.InlineKeyboardButton("💰 Pagar (Mensal)", callback_data="pagar_mensal"),
                        telegram.InlineKeyboardButton("💰 Pagar (Trimestral)", callback_data="pagar_trimestral")
                    ],
                    [telegram.InlineKeyboardButton("📄 Ver Planos", callback_data="planos")],
                    [telegram.InlineKeyboardButton("❓ Ajuda", callback_data="ajuda")]
                ])
            )

        elif texto == "/status":
            dados = carregar_dados()
            info = dados.get(str(user_id))
            if info:
                venc = datetime.strptime(info["vencimento"], "%Y-%m-%d")
                dias = (venc - datetime.now()).days
                BOT.send_message(chat_id=chat_id, text=f"✅ Sua assinatura está ativa. Vence em {dias} dia(s), em {info['vencimento']}.")
            else:
                BOT.send_message(chat_id=chat_id, text="❌ Você não possui uma assinatura ativa.")
        else:
            BOT.send_message(chat_id=chat_id, text="❌ Comando inválido. Por favor, use o menu abaixo:")
            BOT.send_message(
                chat_id=chat_id,
                text="Escolha uma opção:",
                reply_markup=telegram.InlineKeyboardMarkup([
                    [
                        telegram.InlineKeyboardButton("💰 Pagar (Mensal)", callback_data="pagar_mensal"),
                        telegram.InlineKeyboardButton("💰 Pagar (Trimestral)", callback_data="pagar_trimestral")
                    ],
                    [telegram.InlineKeyboardButton("📄 Ver Planos", callback_data="planos")],
                    [telegram.InlineKeyboardButton("❓ Ajuda", callback_data="ajuda")]
                ])
            )

    elif update.callback_query:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        chat_id = query.message.chat.id

        if query.data.startswith("pagar_"):
            plano = query.data.replace("pagar_", "")
            if plano not in PLANOS:
                BOT.send_message(chat_id=chat_id, text="Plano inválido.")
                return "ok"

            plano_info = PLANOS[plano]
            url_base = os.getenv("WEBHOOK_URL")
            if not url_base.endswith("/notificacao"):
                url_base += "/notificacao"

            preference_data = {
                "items": [
                    {
                        "title": f"Assinatura {plano} do grupo",
                        "quantity": 1,
                        "currency_id": "BRL",
                        "unit_price": plano_info["valor"]
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

            salvar_temp_pagamento(preference_id, user_id, plano)
            BOT.send_message(chat_id=chat_id, text="💳 Clique no link abaixo para pagar com Mercado Pago:")
            BOT.send_message(chat_id=chat_id, text=checkout_url)
            BOT.send_message(chat_id=chat_id, text="💡 Após o pagamento, aguarde a confirmação automática aqui mesmo.")

        elif query.data == "planos":
            mensagem = "📋 *Planos disponíveis:*\n\n🔝 Plano Mensal: R$ 19.9 — 30 dias\n🔝 Plano Trimestral: R$ 52.9 — 90 dias"
            BOT.send_message(
                chat_id=chat_id,
                text=mensagem,
                parse_mode=telegram.ParseMode.MARKDOWN,
                reply_markup=telegram.InlineKeyboardMarkup([
                    [telegram.InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu")]
                ])
            )

        elif query.data == "ajuda":
            ajuda_texto = (
                "❓ *Ajuda do Bot*\n\n"
                "- Para *assinar*, clique em \"💰 Pagar (Mensal)\" ou \"💰 Pagar (Trimestral)\".\n"
                "- Para *ver os planos*, clique em \"📄 Ver Planos\".\n"
                "- Em caso de dúvidas, envie um email para: overgeared1959@gmail.com"
            )
            BOT.send_message(
                chat_id=chat_id,
                text=ajuda_texto,
                parse_mode=telegram.ParseMode.MARKDOWN,
                reply_markup=telegram.InlineKeyboardMarkup([
                    [telegram.InlineKeyboardButton("🔙 Voltar", callback_data="voltar_menu")]
                ])
            )

        elif query.data == "voltar_menu":
            BOT.send_message(
                chat_id=chat_id,
                text="Escolha uma opção:",
                reply_markup=telegram.InlineKeyboardMarkup([
                    [
                        telegram.InlineKeyboardButton("💰 Pagar (Mensal)", callback_data="pagar_mensal"),
                        telegram.InlineKeyboardButton("💰 Pagar (Trimestral)", callback_data="pagar_trimestral")
                    ],
                    [telegram.InlineKeyboardButton("📄 Ver Planos", callback_data="planos")],
                    [telegram.InlineKeyboardButton("❓ Ajuda", callback_data="ajuda")]
                ])
            )

    return "ok"

# === Processamento de Pagamento ===

def processar_pagamento(payment_id):
    payment_info = sdk.payment().get(payment_id)
    response = payment_info.get("response", {})
    status = response.get("status")
    preference_id = response.get("preference_id")

    if not preference_id:
        order_id = response.get("order", {}).get("id")
        if order_id:
            try:
                order_info = sdk.merchant_order().get(order_id)
                preference_id = order_info["response"].get("preference_id")
            except Exception as e:
                print(f"Erro ao buscar merchant_order: {e}")

    if not preference_id:
        print("❌ Erro: 'preference_id' não encontrado na resposta do pagamento.")
        return

    temp = carregar_temp_pagamento(preference_id)
    if not temp:
        return

    telegram_id = temp["telegram_id"]
    plano = temp["plano"]
    plano_info = PLANOS.get(plano, {})
    minutos = plano_info.get("minutos")
    dias = plano_info.get("dias", 0)

    if status == "approved" and telegram_id:
        try:
            BOT.get_chat(chat_id=telegram_id)
        except telegram.error.BadRequest:
            print(f"❌ Chat {telegram_id} não encontrado. Pagamento aprovado, mas não foi possível enviar a mensagem.")
            return

        dados = carregar_dados()
        agora = datetime.now()
        hoje = agora.strftime("%Y-%m-%d")

        if minutos:
            vencimento_dt = agora + timedelta(minutes=minutos)
        else:
            vencimento_dt = agora + timedelta(days=dias)

        vencimento = vencimento_dt.strftime("%Y-%m-%d %H:%M:%S")

        dados[str(telegram_id)] = {
            "pagamento": hoje,
            "vencimento": vencimento,
            "status": "ativo"
        }
        salvar_dados(dados)

        BOT.send_message(chat_id=telegram_id, text="✅ Pagamento aprovado! Você foi liberado no grupo.")
        BOT.send_message(chat_id=telegram_id, text=f"☚ Acesse o grupo: {GRUPO_LINK}")

# === Rota de Notificação Mercado Pago ===

@app.route("/notificacao", methods=["POST"])
def notificacao():
    data = request.json
    if not data:
        return "ignorado"

    if data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        processar_pagamento(payment_id)

    elif data.get("type") == "merchant_order":
        order_id = data.get("data", {}).get("id")
        order_info = sdk.merchant_order().get(order_id)
        payments = order_info["response"].get("payments", [])

        for payment in payments:
            if payment["status"] == "approved":
                payment_id = payment["id"]
                processar_pagamento(payment_id)

    return "ok"
# === Verificação Diária de Vencimentos (ajustada para 10 minutos e notificação 4 minutos antes) ===

def verificar_vencimentos():
    while True:
        time.sleep(30)
        dados = carregar_dados()
        agora = datetime.now()

        for uid, info in list(dados.items()):
            if info["status"] == "ativo":
                try:
                    vencimento_dt = datetime.strptime(info["vencimento"], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    vencimento_dt = datetime.strptime(info["vencimento"], "%Y-%m-%d")

                minutos_restantes = int((vencimento_dt - agora).total_seconds() // 60)

                if minutos_restantes == 4:
                    try:
                        BOT.send_message(chat_id=int(uid), text="⏳ Sua assinatura expira em 4 minutos. Renove para continuar no grupo sem interrupções.")
                    except Exception as e:
                        print(f"Erro ao avisar {uid}: {e}")

                if vencimento_dt <= agora:
                    try:
                        BOT.send_message(chat_id=int(uid), text="⚠️ Sua assinatura expirou. Você será removido do grupo.")
                        BOT.ban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                        BOT.unban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                    except Exception as e:
                        print(f"Erro ao remover {uid}: {e}")
                    dados[uid]["status"] = "inativo"

        salvar_dados(dados)
# === Iniciar verificação e app Flask ===

verificacao_thread = Thread(target=verificar_vencimentos)
verificacao_thread.daemon = True
verificacao_thread.start()

if __name__ == '__main__':
    print("Rodando localmente. Em produção, use gunicorn.")
    app.run(host='0.0.0.0', port=5000)
