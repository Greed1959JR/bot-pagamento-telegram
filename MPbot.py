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

ASSINATURA_VALOR = 10.00
DIAS_ASSINATURA = 1
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

def salvar_temp_pagamento(preference_id, telegram_id):
    with lock:
        if os.path.exists(TEMP_PREFS):
            with open(TEMP_PREFS, 'r') as f:
                dados = json.load(f)
        else:
            dados = {}
        dados[preference_id] = telegram_id
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
        if uid_remover in dados:
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
        <form method='post'>
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
        html += f"<li><b>{nome}</b> (ID: {uid}) — Pagamento: {pagamento_fmt} | Vencimento: {vencimento_fmt} | Status: {info['status']} <button name='remover' value='{uid}'>Remover</button></li>"

    html += """
        </ul>
        </form>
    """
    return html

# === Resto do código permanece igual ===
# (webhook, pagamento, notificacao, verificação, etc...)
