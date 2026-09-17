from flask import Blueprint, request, render_template, redirect, url_for, session, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from flask_bcrypt import check_password_hash, generate_password_hash
from core.db import fetch,execute

auth=Blueprint('auth',__name__)
manager=LoginManager()
manager.login_view='auth.login'
DUMMY=generate_password_hash('senha-inexistente').decode()
class User(UserMixin):
    def __init__(self,email):self.id=email
@manager.user_loader
def load(email):
    rows=fetch('SELECT email FROM usuarios WHERE email=%s',(email,))
    return User(rows[0]['email']) if rows else None

@auth.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower();password=request.form.get('password','')
        ip=request.remote_addr or 'local'
        tries=fetch("SELECT quantidade FROM login_tentativas WHERE ip=%s AND atualizado>now()-interval '5 minutes'",(ip,))
        if tries and tries[0]['quantidade']>=10:
            flash('Muitas tentativas. Aguarde cinco minutos.','error')
            return render_template('login.html',title='Entrar'),429
        rows=fetch('SELECT email,senha_hash FROM usuarios WHERE email=%s',(email,))
        valid=False
        if len(password.encode('utf-8'))<=72:
            valid=check_password_hash(rows[0]['senha_hash'] if rows else DUMMY,password)
        if rows and valid:
            session.clear();session.permanent=True;login_user(User(rows[0]['email']))
            execute('DELETE FROM login_tentativas WHERE ip=%s',(ip,))
            return redirect(url_for('pages.home'))
        execute("INSERT INTO login_tentativas(ip,quantidade) VALUES(%s,1) ON CONFLICT(ip) DO UPDATE SET quantidade=CASE WHEN login_tentativas.atualizado<now()-interval '5 minutes' THEN 1 ELSE login_tentativas.quantidade+1 END, atualizado=now()",(ip,))
        flash('E-mail ou senha incorretos.','error')
        return render_template('login.html',title='Entrar'),401
    return render_template('login.html',title='Entrar')

@auth.post('/logout')
@login_required
def logout():
    logout_user();session.clear()
    return redirect(url_for('auth.login'))
