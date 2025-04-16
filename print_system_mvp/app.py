from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import uuid
import time
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'chave_secreta_temporaria'

users = {}
planos_data = {
    'basico': {'nome': 'Básico', 'limite': 50, 'preco': 19.90, 'validade_dias': 30},
    'simples': {'nome': 'Simples', 'limite': 100, 'preco': 35.50, 'validade_dias': 30},
    'avancado': {'nome': 'Avançado', 'limite': 200, 'preco': 59.90, 'validade_dias': 30},
    'premium': {'nome': 'Premium', 'limite': 500, 'preco': 124.90, 'validade_dias': 30},
}
user_plans = {}
user_usage = {}
pending_orders = {} # Código do pedido: {'email': ..., 'plan_name': ..., 'created_at': ...}
payment_timers = {} # email: {'order_code': ..., 'expiry_time': datetime}

# QR Code Pix estático
STATIC_PIX_QR_CODE = ""

# Usuário administrador
ADMIN_USER = {'email': 'admin@willyprint.com', 'password': 'admin123'}

PAYMENT_TIMEOUT_SECONDS = 60 * 60  # 1 hora

def verificar_expiracao_planos():
    usuarios_a_remover = []
    for email, plano_info in user_plans.items():
        if datetime.utcnow() > plano_info['data_expiracao']:
            usuarios_a_remover.append(email)

    for email in usuarios_a_remover:
        del user_plans[email]
        if email in users:
            users[email]['payment_status'] = 'expired'
            print(f"Plano expirado e removido para o usuário: {email}")

def verificar_timers_pagamento():
    usuarios_a_remover = []
    for email, timer_info in payment_timers.items():
        if datetime.utcnow() > timer_info['expiry_time']:
            usuarios_a_remover.append(email)

    for email in usuarios_a_remover:
        del payment_timers[email]
        print(f"Timer de pagamento expirado para o usuário: {email}")

@app.before_request
def before_request():
    verificar_expiracao_planos()
    verificar_timers_pagamento()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in users:
            return render_template('register.html', error='Email já cadastrado.')
        users[email] = {'password': password, 'payment_status': 'pending'}
        user_usage[email] = 0
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in users and users[email]['password'] == password:
            session['email'] = email
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Email ou senha incorretos.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('email', None)
    return redirect(url_for('index'))

@app.route('/plans')
def plans():
    if 'email' not in session:
        return redirect(url_for('login'))
    return render_template('plans.html', planos_data=planos_data, user_plan=user_plans.get(session['email']))

@app.route('/pay/<plan_name>')
def pay(plan_name):
    if 'email' not in session:
        return redirect(url_for('login'))

    email = session['email']

    if email in payment_timers:
        timer_info = payment_timers[email]
        expiry_time_str = timer_info['expiry_time'].strftime('%Y-%m-%d %H:%M:%S')
        return render_template('pix_payment_page.html', payment_details={
            'qr_code': STATIC_PIX_QR_CODE,
            'chave_pix': "(38) 99733-3443", # Substitua pela sua chave real
            'valor': planos_data[plan_name]['preco'],
            'descricao': f"Pagamento plano {planos_data[plan_name]['nome']}",
            'order_code': timer_info['order_code'],
            'expiry_time': expiry_time_str
        }, plan_name=plan_name, active_timer=True)

    if plan_name in planos_data:
        order_code = str(uuid.uuid4())
        expiry_time = datetime.utcnow() + timedelta(seconds=PAYMENT_TIMEOUT_SECONDS)
        payment_timers[email] = {
            'order_code': order_code,
            'expiry_time': expiry_time
        }
        pending_orders[order_code] = {
            'email': email,
            'plan_name': plan_name,
            'created_at': datetime.utcnow()
        }
        payment_details = {
            'qr_code': STATIC_PIX_QR_CODE,
            'chave_pix': "(38) 99733-3443", # Substitua pela sua chave real
            'valor': planos_data[plan_name]['preco'],
            'descricao': f"Pagamento plano {planos_data[plan_name]['nome']}",
            'order_code': order_code,
            'expiry_time': expiry_time.strftime('%Y-%m-%d %H:%M:%S')
        }
        return render_template('pix_payment_page.html', payment_details=payment_details, plan_name=plan_name, active_timer=False)
    return "Plano inválido."

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email == ADMIN_USER['email'] and password == ADMIN_USER['password']:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin/login.html', error='Credenciais inválidas.')
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    return render_template('admin/dashboard.html', pending_orders=pending_orders, planos_data=planos_data, users=users, user_plans=user_plans)

@app.route('/admin/release_plan/<order_code>')
def admin_release_plan(order_code):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    order_info = pending_orders.pop(order_code, None)
    if order_info:
        email = order_info['email']
        plan_name = order_info['plan_name']
        if email in users:
            users[email]['payment_status'] = 'active'
            plan = planos_data[plan_name]
            data_ativacao = datetime.utcnow()
            data_expiracao = data_ativacao + timedelta(days=plan['validade_dias'])
            user_plans[email] = {'nome': plan_name, 'data_ativacao': data_ativacao, 'data_expiracao': data_expiracao}
            user_usage[email] = 0
            if email in payment_timers and payment_timers[email]['order_code'] == order_code:
                del payment_timers[email]
            print(f"Plano liberado manualmente para o usuário: {email} (Pedido: {order_code}, Plano: {plan_name}, Expira em: {data_expiracao})")
        else:
            print(f"Erro ao liberar plano: Usuário com email {email} não encontrado.")
            # Você pode adicionar alguma lógica adicional aqui, como exibir uma mensagem de erro ao administrador
    return redirect(url_for('admin_dashboard'))

@app.route('/dashboard')
def dashboard():
    if 'email' not in session:
        return redirect(url_for('login'))
    email = session['email']
    plano_info = user_plans.get(email)
    plan = planos_data.get(plano_info['nome']) if plano_info else None
    usage = user_usage.get(email, 0)
    remaining = plan['limite'] - usage if plan else 0
    data_expiracao = plano_info['data_expiracao'].strftime('%d/%m/%Y %H:%M:%S') if plano_info else None
    return render_template('dashboard.html', plan=plan, usage=usage, remaining=remaining, data_expiracao=data_expiracao)

@app.route('/admin/remove_plan/<email>')
def admin_remove_plan(email):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    if email in user_plans:
        del user_plans[email]
        users[email]['payment_status'] = 'pending' # Ou outra lógica de status
        print(f"Plano removido para o usuário: {email}")
        # Adicione qualquer outra lógica necessária, como logs, mensagens ao usuário, etc.
    else:
        print(f"Nenhum plano ativo encontrado para o usuário: {email}")

    return redirect(url_for('admin_dashboard')) # Ou outra página administrativa

@app.route('/print_page', methods=['POST'])
def print_page():
    if 'email' not in session:
        return redirect(url_for('login'))
    email = session['email']
    user = users.get(email)
    plano_info = user_plans.get(email)
    if user and user['payment_status'] == 'active' and plano_info:
        plan = planos_data[plano_info['nome']]
        if email in user_usage and user_usage[email] < plan['limite']:
            user_usage[email] += 1
    else:
        print(f"Impressão bloqueada para {email}: pagamento pendente, plano inativo ou inexistente.")
    return redirect(url_for('dashboard'))

@app.route('/change_plan', methods=['GET'])
def change_plan():
    if 'email' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('plans'))

@app.route('/admin/adjust_usage', methods=['POST'])
def admin_adjust_usage():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    email = request.form['email']
    pages_str = request.form['pages']
    action = request.form['action']

    if not pages_str.isdigit():
        session['error_message'] = "Por favor, insira um número válido de páginas."
        return redirect(url_for('admin_dashboard'))

    pages = int(pages_str)

    if email in user_usage:
        if action == 'add':
            user_usage[email] += pages
            print(f"Adicionadas {pages} páginas para {email}. Novo uso: {user_usage[email]}")
        elif action == 'remove':
            if user_usage[email] >= pages:
                user_usage[email] -= pages
                print(f"Removidas {pages} páginas para {email}. Novo uso: {user_usage[email]}")
            else:
                session['error_message'] = f"Não é possível remover {pages} páginas. Uso atual: {user_usage[email]}."
                return redirect(url_for('admin_dashboard'))
        else:
            session['error_message'] = "Ação inválida."
            return redirect(url_for('admin_dashboard'))

        session.pop('error_message', None)
    else:
        session['error_message'] = "Usuário não encontrado."

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject_plan/<order_code>')
def admin_reject_plan(order_code):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    if order_code in pending_orders:
        email = pending_orders[order_code]['email']
        if email in payment_timers and payment_timers[email]['order_code'] == order_code:
            del payment_timers[email]
        del pending_orders[order_code]
        print(f"Pedido de pagamento recusado: {order_code}")
        # Adicione qualquer outra lógica necessária, como notificar o usuário (opcional)
    else:
        print(f"Código de pedido não encontrado: {order_code}")

    return redirect(url_for('admin_dashboard'))

@app.route('/cancel_and_change_plan', methods=['POST'])
def cancel_and_change_plan():
    if 'email' not in session:
        return redirect(url_for('login'))
    email = session['email']
    if email in user_plans:
        print(f"Plano do usuário {email} foi cancelado.")
        del user_plans[email]
        users[email]['payment_status'] = 'pending'
        session['cancel_success'] = "Seu plano foi cancelado com sucesso. Escolha um novo plano abaixo."
    else:
        session['cancel_success'] = "Você não possui um plano ativo para cancelar."
    return redirect(url_for('plans'))

if __name__ == '__main__':
    app.run(debug=True)