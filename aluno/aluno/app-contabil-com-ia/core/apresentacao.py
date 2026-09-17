"""Apresentação monetária compartilhada. Nunca altera os valores de negócio."""
from flask import g, request
from flask_login import current_user
from markupsafe import Markup
from core.db import fetch
from core.dre_gerencial import formatar_valor

RELATORIOS = frozenset(('balancete', 'balanco', 'razao', 'dre',
                       'dre-gerencial', 'dmpl', 'dfc', 'dfc-direto', 'dfc-indireto', 'analise', 'orcamento', 'conciliacao'))


def preferencias():
    if not hasattr(g, 'apresentacao_relatorios'):
        registros = fetch('SELECT chave,valor FROM preferencias_ui WHERE email=%s AND chave IN (%s,%s)',
                          (current_user.get_id(), 'relatorios_apresentacao', 'dre_apresentacao')) if current_user.is_authenticated else []
        valores = {r['chave']: r['valor'] for r in registros}
        # A preferência global assume a escolha anterior da DRE até a primeira alteração.
        antiga = valores.get('relatorios_apresentacao', valores.get('dre_apresentacao', {}))
        g.apresentacao_relatorios = {k: antiga.get(k) is True for k in ('mil', 'centavos')}
    return g.apresentacao_relatorios


def contexto():
    endpoint = request.endpoint or ''
    ativo = (request.view_args or {}).get('active')
    habilitado = (endpoint == 'pages.screen' and ativo in RELATORIOS) or endpoint in (
        'grupos_dre.demonstracao', 'titulos.resultado', 'titulos.detalhe')
    return {'report_format': preferencias() if habilitado and current_user.is_authenticated else None}


def moeda(valor, formato, prefixo=False):
    bruto = '' if valor is None else str(int(valor))
    unidade = 'R$ mil' if formato['mil'] else 'R$'
    numero = Markup('<span data-report-money="{}">{}</span>').format(
        bruto, formatar_valor(valor, **formato))
    if prefixo and valor is not None:
        return Markup('<span data-report-unit>{}</span> {}').format(unidade, numero)
    return numero
