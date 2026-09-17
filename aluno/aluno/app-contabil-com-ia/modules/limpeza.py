from flask import Blueprint, abort, flash, redirect, render_template, request, url_for, session
from flask_login import login_required

from core.limpeza import limpar_dados_negocio


limpeza = Blueprint('limpeza', __name__)


@limpeza.get('/limpar')
@login_required
def pagina():
    return render_template('limpar.html', title='Limpar dados', active='limpar')


@limpeza.post('/limpar')
@login_required
def executar():
    if request.form.get('confirmacao') != 'LIMPAR DADOS':
        abort(400, description='Digite LIMPAR DADOS para confirmar a limpeza.')
    limpar_dados_negocio()
    session.pop('importacao_token', None)
    flash('Dados removidos. Importe uma planilha para recomeçar.', 'success')
    return redirect('/importar')
