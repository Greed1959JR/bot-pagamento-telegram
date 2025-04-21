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
 
 
 DB_FILE = "assinantes.json"
 TEMP_PREFS = "pagamentos_temp.json"
 
 app = Flask(__name__)
 sdk = mercadopago.SDK(ACCESS_TOKEN)
 lock = Lock()
 
 PLANOS = {
     "mensal": {"valor": 19.90, "dias": 30},
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
 
 import os
 
 USUARIO_ADMIN = os.getenv("USUARIO_ADMIN")
 SENHA_ADMIN = os.getenv("SENHA_ADMIN")
 
 @app.route("/logout")
 def logout():
     return Response("Logout realizado.", 401, {"WWW-Authenticate": "Basic realm='Login Requerido'"})
 
 @app.route("/painel", methods=["GET", "POST"])
 def painel():
     auth = request.authorization
     if not auth or auth.username != USUARIO_ADMIN or auth.password != SENHA_ADMIN:
         return Response("Acesso negado", 401, {"WWW-Authenticate": "Basic realm='Login Requerido'"})
 
     dados = carregar_dados()
 
     # Processar ações do formulário
     if request.method == "POST":
         # Remover usuário
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
 
         # Adicionar usuário manualmente
         novo_id = request.form.get("novo_id")
         novo_nome = request.form.get("novo_nome")
         novo_plano = request.form.get("novo_plano")
         if novo_id and novo_nome and novo_plano:
             dias = PLANOS.get(novo_plano, {}).get("dias", 30)
             hoje = datetime.now()
             vencimento = hoje + timedelta(days=dias)
             dados[novo_id] = {
                 "nome": novo_nome,
                 "pagamento": hoje.strftime("%Y-%m-%d"),
                 "vencimento": vencimento.strftime("%Y-%m-%d"),
                 "status": "ativo"
             }
             salvar_dados(dados)
             return redirect(url_for('painel'))
 
         # Gerar link de convite
         gerar_link_id = request.form.get("gerar_link")
         if gerar_link_id:
             try:
                 link_convite = BOT.create_chat_invite_link(
                     chat_id=GROUP_ID,
                     expire_date=int((datetime.now() + timedelta(minutes=10)).timestamp()),
                     member_limit=1
                 ).invite_link
                 BOT.send_message(chat_id=int(gerar_link_id), text=f"🔗 Acesse o grupo com este link (válido por 10 min, 1 uso):\n{link_convite}")
             except Exception as e:
                 print(f"Erro ao gerar link para {gerar_link_id}: {e}")
             return redirect(url_for('painel'))
 
     filtro = request.args.get("filtro", "ativos")
     html = f"""
         <html>
         <head>
             <title>Painel de Assinantes</title>
             <style>
                 body {{ font-family: 'Segoe UI', sans-serif; background: #ecf0f1; padding: 30px; }}
                 h2 {{ color: #2c3e50; }}
                 .ativo {{ color: green; }}
                 .inativo {{ color: red; }}
                 select, input[type=text], input[type=submit], button {{ padding: 8px; margin: 5px 0; border-radius: 6px; border: 1px solid #ccc; width: 100%; }}
                 .container {{ background: white; padding: 25px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.15); max-width: 800px; margin: auto; }}
                 .user-card {{ margin: 15px 0; padding: 15px; border-left: 5px solid #3498db; background: #fdfdfd; border-radius: 6px; }}
                 .btn-remove {{ background: #e74c3c; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }}
                 .btn-link {{ background: #2ecc71; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }}
                 .btn-logout {{ background: #95a5a6; color: white; border: none; padding: 6px 12px; border-radius: 4px; margin-top: 15px; cursor: pointer; width: auto; }}
                 .add-form {{ background: #f8f8f8; padding: 20px; border: 1px solid #ddd; border-radius: 10px; margin-top: 20px; }}
                 label {{ display: block; margin-top: 10px; }}
             </style>
         </head>
         <body>
             <div class='container'>
             <h2>Painel de Assinantes ({filtro.title()}):</h2>
             <form method='get'>
                 <select name='filtro' onchange='this.form.submit()'>
                     <option value='ativos' {'selected' if filtro == 'ativos' else ''}>Ativos</option>
                     <option value='inativos' {'selected' if filtro == 'inativos' else ''}>Inativos</option>
                     <option value='todos' {'selected' if filtro == 'todos' else ''}>Todos</option>
                 </select>
             </form>
             <form action='/logout' method='get'>
                 <button class='btn-logout'>🔐 Sair</button>
             </form>
 
             <div class='add-form'>
                 <h3>Adicionar Usuário Manualmente</h3>
                 <form method='post'>
                     <label>ID Telegram:</label>
                     <input type='text' name='novo_id' required>
                     <label>Nome:</label>
                     <input type='text' name='novo_nome' required>
                     <label>Plano:</label>
                     <select name='novo_plano' required>
                         <option value='mensal'>Mensal</option>
                         <option value='trimestral'>Trimestral</option>
                     </select><br><br>
                     <input type='submit' value='Adicionar Assinante'>
                 </form>
             </div>
 
             <form method='post' onsubmit="return confirm('Tem certeza que deseja remover este usuário?');">
     """
 
     for uid, info in dados.items():
         if filtro == "ativos" and info.get("status") != "ativo":
             continue
         if filtro == "inativos" and info.get("status") != "inativo":
             continue
 
         nome = info.get("nome", "Desconhecido")
         pagamento = datetime.strptime(info["pagamento"], "%Y-%m-%d")
         vencimento = datetime.strptime(info["vencimento"], "%Y-%m-%d")
         status = info["status"]
 
         agora = datetime.now()
         tempo_restante = vencimento - agora
         dias = tempo_restante.days
         horas = tempo_restante.seconds // 3600
         minutos = (tempo_restante.seconds % 3600) // 60
         tempo_fmt = f"{dias}d {horas}h {minutos}m" if tempo_restante.total_seconds() > 0 else "Expirado"
 
         html += f"""
             <div class='user-card'>
                 <b>{nome}</b> (ID: {uid})<br>
                 <b>Pagamento:</b> {pagamento.strftime("%d/%m/%Y")} | 
                 <b>Vencimento:</b> {vencimento.strftime("%d/%m/%Y")}<br>
                 <b>Status:</b> <span class="{status}">{status.title()}</span><br>
                 <b>Tempo restante:</b> {tempo_fmt}<br>
                 <button class='btn-remove' name='remover' value='{uid}'>Remover</button>
                 <input type='hidden' name='confirmar_remover' value='{uid}'>
                 <button class='btn-link' name='gerar_link' value='{uid}'>Gerar Link de Acesso</button>
             </div>
         """
 
     html += """
             </form>
             </div>
         </body>
         </html>
     """
     return html
 
 
 # === Webhook Telegram ===
 
 @app.route("/", methods=["GET", "POST", "HEAD"])
 def webhook():
     if request.method in ["GET", "HEAD"]:
         return "Bot de pagamento está ativo."
 
     update = telegram.Update.de_json(request.get_json(force=True), BOT)
 
     if update.message and update.message.text:
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
                 "- Em caso de dúvidas, envie um email para: overgeared1959@gmail.com\n"
                 "- Ou acesse o Telegram: [@overgeared_tips](https://web.telegram.org/k/#@overgeared_tips)"
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
     dias = PLANOS.get(plano, {}).get("dias", 30)
 
     if status == "approved" and telegram_id:
         try:
             BOT.get_chat(chat_id=telegram_id)
         except telegram.error.BadRequest:
             print(f"❌ Chat {telegram_id} não encontrado. Pagamento aprovado, mas não foi possível enviar a mensagem.")
             return
 
         dados = carregar_dados()
         hoje = datetime.now().strftime("%Y-%m-%d")
         vencimento = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
 
         dados[str(telegram_id)] = {
             "pagamento": hoje,
             "vencimento": vencimento,
             "status": "ativo"
         }
         salvar_dados(dados)
 
         try:
             link_convite = BOT.create_chat_invite_link(
                 chat_id=GROUP_ID,
                 expire_date=int((datetime.now() + timedelta(minutes=10)).timestamp()),
                 member_limit=1
             ).invite_link
             BOT.send_message(chat_id=telegram_id, text="✅ Pagamento aprovado! Você foi liberado no grupo.")
             BOT.send_message(
     chat_id=telegram_id,
     text=f"☚ Acesse o grupo com este link (válido por 10 minutos e para 1 uso):\n{link_convite}"
 )
         except Exception as e:
             print(f"Erro ao criar link de convite: {e}")
             BOT.send_message(chat_id=telegram_id, text="⚠️ Pagamento aprovado, mas houve erro ao gerar o link de convite. Contate o suporte.")
 
 
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
 
 # === Verificação Diária de Vencimentos ===
 
 def verificar_vencimentos():
     while True:
         time.sleep(30)
         dados = carregar_dados()
         hoje = datetime.now().strftime("%Y-%m-%d")
 
         for uid, info in list(dados.items()):
             if info["status"] == "ativo":
                 dias_restantes = (datetime.strptime(info["vencimento"], "%Y-%m-%d") - datetime.now()).days
                 if dias_restantes == 1:
                     try:
                         BOT.send_message(chat_id=int(uid), text="⏳ Sua assinatura vence amanhã. Renove para continuar no grupo sem interrupções.")
                     except Exception as e:
                         print(f"Erro ao avisar {uid}: {e}")
                 if info["vencimento"] < hoje:
                     try:
                         BOT.send_message(chat_id=int(uid), text="⚠️ Sua assinatura expirou. Você será removido do grupo.")
                         BOT.ban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                         BOT.unban_chat_member(chat_id=GROUP_ID, user_id=int(uid))
                     except Exception as e:
                         print(f"Erro ao remover {uid}: {e}")
                     dados[uid]["status"] = "inativo"
 
         salvar_dados(dados)
 
 verificacao_thread = Thread(target=verificar_vencimentos)
 verificacao_thread.daemon = True
 verificacao_thread.start()
 if __name__ == '__main__':
     print("Rodando localmente. Em produção, use gunicorn.")
     app.run(host='0.0.0.0', port=5000)
