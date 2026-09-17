import json
import os
from pathlib import Path
from flask import Flask, render_template, request
from flask_login import current_user
from core.auth import auth, manager
from core.security import init_security, csrf_token
from core.db import fetch
from modules.pages import pages,NAV,MENU_GRUPOS
from modules.importar import importacao
from modules.cadastros import cadastros
from modules.grupos_dre import grupos_dre
from modules.limpeza import limpeza
from modules.conciliacao_titulos import titulos
from modules.analise_financeira import analise_financeira
from modules.configuracao_ia import configuracao_ia
from modules.configuracoes import configuracoes
from modules.ecf import ecf
from modules.efd import efd
from modules.esocial import esocial
from core.configuracao_ia import efetiva as configuracao_nvidia
from jinja2 import pass_context
from core.modulos import instalar, filtrar_nav, filtrar_grupos, disponivel
from core.apresentacao import contexto as contexto_apresentacao, moeda

RAIZ_APP = Path(__file__).resolve().parent
NOME_APP_PADRAO = "APP CONTÁBIL COM IA"


def nome_app() -> str:
    """Lê somente a configuração de apresentação; falha volta à marca padrão."""
    try:
        conteudo = (RAIZ_APP / "config" / "app.json").read_text(encoding="utf-8")
        valor = json.loads(conteudo).get("nome_app")
    except (OSError, json.JSONDecodeError):
        valor = None
    if isinstance(valor, str):
        valor = " ".join(valor.split())
        if 3 <= len(valor) <= 60 and all(ord(caractere) >= 32 for caractere in valor):
            return valor
    return NOME_APP_PADRAO

def money(v):
    if v is None:return 'Sem realizado'
    v=int(v);n=abs(v);s=f'{n//100:,}'.replace(',','.')+f',{n%100:02}'
    return ('− ' if v<0 else '')+'R$ '+s

def create_app():
    app=Flask(__name__)
    instalar(app)
    secret=os.environ.get('SECRET_KEY','')
    if len(secret)<32:raise RuntimeError('Configure SECRET_KEY com pelo menos 32 caracteres aleatórios.')
    if not os.environ.get('DATABASE_URL'):raise RuntimeError('Configure DATABASE_URL.')
    mode=os.environ.get('APP_ENV','production')
    if mode not in ('production','development'):raise RuntimeError('APP_ENV deve ser production ou development.')
    app.config.update(SECRET_KEY=secret,PRODUCTION=mode=='production')
    app.config['NVIDIA_CONFIG_LOADER'] = configuracao_nvidia
    init_security(app);manager.init_app(app)
    app.register_blueprint(auth);app.register_blueprint(importacao);app.register_blueprint(cadastros);app.register_blueprint(grupos_dre);app.register_blueprint(limpeza);app.register_blueprint(titulos);app.register_blueprint(pages)
    app.register_blueprint(analise_financeira)
    app.register_blueprint(configuracao_ia)
    app.register_blueprint(configuracoes)
    app.register_blueprint(ecf)
    app.register_blueprint(efd)
    app.register_blueprint(esocial)
    @pass_context
    def money_display(ctx, v):
        return moeda(v, ctx['report_format'], prefixo=True) if ctx.get('report_format') is not None else money(v)
    app.jinja_env.filters['money']=money_display
    @pass_context
    def money_num(ctx, v):
        if ctx.get('report_format') is not None:return moeda(v, ctx['report_format'])
        if v is None:return '—'
        n=abs(int(v));s=f'{n//100:,}'.replace(',','.')+f',{n%100:02}'
        return '('+s+')' if v<0 else s
    app.jinja_env.filters['money_num']=money_num
    def data_br(v):
        if not v:return 'Sem dado'
        s=v.isoformat() if hasattr(v,'isoformat') else str(v)
        return s[8:10]+'/'+s[5:7]+'/'+s[:4] if len(s)>=10 else s
    app.jinja_env.filters['data_br']=data_br
    app.context_processor(contexto_apresentacao)
    @app.context_processor
    def context():
        return dict(csrf_token=csrf_token(),user_email=current_user.get_id() if current_user.is_authenticated else '',nav=filtrar_nav(NAV),menu_grupos=filtrar_grupos(MENU_GRUPOS),modulo_disponivel=disponivel,getparam=request.args.get,app_nome=nome_app())
    @app.get('/health')
    def health():
        fetch('SELECT 1');return {'status':'ok'}
    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(500)
    def erro(e):
        return render_template('error.html',title='Não foi possível concluir',message=e.description if e.code!=500 else 'Erro interno. Os dados não foram alterados por esta solicitação.',error=e.description,code=e.code),e.code
    return app

app=create_app()
if __name__=='__main__':
    from waitress import serve
    serve(app,host=os.environ.get('HOST','127.0.0.1'),port=int(os.environ.get('PORT','8080')))
