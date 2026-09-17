"""Testar uma configuração candidata antes de ativá-la, sem persistir o segredo no teste."""
import hashlib
import hmac
import json
import threading
import time
from flask import Blueprint, render_template, request, redirect, flash, jsonify, current_app, session
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadData
from core import configuracao_ia as config, nvidia_chat
from core.modelos_ia import MODELOS, MODELO_PADRAO

configuracao_ia = Blueprint('configuracao_ia', __name__)
_testes = {}
_catalogos = {}
_lock = threading.Lock()


def _assinador():
    return URLSafeTimedSerializer(current_app.secret_key, salt='configuracao-ia-testada-v1')


def _identidade(cfg):
    # O recibo leva só HMAC, nunca a chave em cookie, HTML ou armazenamento do navegador.
    valor = json.dumps([cfg['chave'], cfg['modelo'], current_user.get_id(), session.get('csrf_token')], ensure_ascii=True)
    return hmac.new(current_app.secret_key.encode(), valor.encode(), hashlib.sha256).hexdigest()


def _exigir_teste(cfg, recibo):
    try:
        registro = _assinador().loads(recibo, max_age=900)
        if not isinstance(registro, str) or not hmac.compare_digest(registro, _identidade(cfg)):
            raise ValueError
    except (BadData, ValueError, TypeError):
        raise ValueError('Teste esta chave e este modelo com sucesso antes de salvar. O teste vale por 15 minutos.') from None


@configuracao_ia.route('/configuracao-ia', methods=['GET', 'POST'])
@login_required
def pagina():
    erro = None
    if request.method == 'POST':
        if request.content_length and request.content_length > 5000:
            return 'Configuração muito longa.', 413
        try:
            candidata = config.candidata(request.form.get('chave', ''), _modelo_enviado())
            _exigir_teste(candidata, request.form.get('teste_token', ''))
            config.salvar(candidata['chave'], candidata['modelo'])
        except ValueError as exc:
            erro = str(exc)
        else:
            flash('Configuração testada e salva. Já está em uso na análise financeira.', 'success')
            return redirect('/configuracao-ia', code=303)
    cfg = nvidia_chat.status()
    selecionado = (_modelo_enviado() if request.method == 'POST' else cfg['modelo'] if cfg['configurada'] else '')[:120]
    return render_template('configuracao_ia.html', title='Configuração da IA', active='configuracao-ia',
                           ia=cfg, erro=erro, modelo=selecionado, modelos=MODELOS,
                           recomendado=MODELO_PADRAO, modelo_fora_catalogo=selecionado and selecionado not in {m['id'] for m in MODELOS}), 400 if erro else 200


@configuracao_ia.post('/api/configuracao-ia/testar')
@login_required
def testar():
    if request.content_length and request.content_length > 5000:
        return jsonify(ok=False, mensagem='Configuração muito longa.'), 413
    try:
        candidata = config.candidata(request.form.get('chave', ''), _modelo_enviado())
    except ValueError as exc:
        return jsonify(ok=False, mensagem=str(exc)), 400
    usuario = current_user.get_id()
    with _lock:
        agora = time.monotonic()
        if agora - _testes.get(usuario, 0) < 25:
            return jsonify(ok=False, mensagem='Aguarde alguns segundos antes de testar novamente.'), 429
        _testes[usuario] = agora
    inicio = time.monotonic()
    try:
        nvidia_chat.testar_conexao(candidata)
    except nvidia_chat.ServicoIA as exc:
        return jsonify(ok=False, mensagem=str(exc), codigo=exc.codigo, http_provedor=exc.http_status), 502
    segundos = round(time.monotonic() - inicio, 1)
    return jsonify(ok=True, teste_token=_assinador().dumps(_identidade(candidata)),
                   mensagem=f'Modelo respondeu em {segundos:.1f} s. Teste aprovado; agora clique em Salvar configuração.'.replace('.0 s', ',0 s'))


def _modelo_enviado():
    valor = request.form.get('modelo', '')
    return request.form.get('modelo_manual', '') if valor == '__manual__' else valor


@configuracao_ia.post('/api/configuracao-ia/modelos')
@login_required
def modelos_disponiveis():
    if request.content_length and request.content_length > 5000:
        return jsonify(ok=False, mensagem='Configuração muito longa.'), 413
    try:
        candidata = config.candidata(request.form.get('chave', ''), MODELO_PADRAO)
    except ValueError as exc:
        return jsonify(ok=False, mensagem=str(exc)), 400
    # Guarda somente IDs públicos e HMAC da chave por dois minutos, evitando
    # que recarregar a tela volte à lista inicial por causa do intervalo mínimo.
    identidade = hmac.new(current_app.secret_key.encode(), candidata['chave'].encode(), hashlib.sha256).hexdigest()
    with _lock:
        agora = time.monotonic()
        anterior = _catalogos.get(identidade)
        if anterior and anterior['expira'] > agora:
            return _resposta_catalogo(anterior['modelos'])
        usuario = (current_user.get_id(), 'catalogo')
        if agora - _testes.get(usuario, 0) < 10:
            return jsonify(ok=False, mensagem='Aguarde alguns segundos para atualizar o catálogo novamente.'), 429
        _testes[usuario] = agora
    try:
        modelos = nvidia_chat.listar_modelos(candidata)
    except nvidia_chat.ServicoIA as exc:
        return jsonify(ok=False, mensagem=str(exc), codigo=exc.codigo, http_provedor=exc.http_status), 502
    with _lock:
        if len(_catalogos) >= 128:
            _catalogos.pop(next(iter(_catalogos)))
        _catalogos[identidade] = {'modelos': modelos, 'expira': time.monotonic() + 120}
    return _resposta_catalogo(modelos)


def _resposta_catalogo(modelos):
    return jsonify(ok=True, modelos=modelos,
                   mensagem=f'{len(modelos)} modelos no catálogo NVIDIA. O teste confirma a compatibilidade com este app.')
