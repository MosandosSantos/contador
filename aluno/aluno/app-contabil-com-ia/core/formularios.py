"""Respostas de edição sem descartar o formulário quando há erro."""
from flask import request, jsonify, flash, redirect


def resposta_edicao(mensagem, destino, erro=False):
    if request.headers.get('X-Record-Modal') == '1':
        if not erro:
            flash(mensagem, 'success')
        return jsonify(ok=not erro, message=mensagem), 422 if erro else 200
    flash(mensagem, 'error' if erro else 'success')
    return redirect(destino)
