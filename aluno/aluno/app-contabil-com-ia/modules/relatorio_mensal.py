"""Relatório narrativo mensal (R3): números calculados localmente + texto da IA quando configurada."""
from calendar import monthrange
from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from core.db import fetch
from core.ia_texto import chat_da_analise, frase_hibrida
from core.insights import variacoes_conta, caixa_destaque

bp = Blueprint('relatorio_mensal', __name__, url_prefix='/relatorio-mensal')


def _competencia_padrao(mov):
    comps = {str(m['data'])[:7] for m in mov}
    return max(comps) if comps else date.today().strftime('%Y-%m')


def _fechamento(mov, ids, ate):
    return sum(m['debito_centavos'] - m['credito_centavos'] for m in mov
               if str(m['data']) <= ate and m['conta_id'] in ids)


def _periodo_do_mes(competencia):
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    return date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])


def _resultado_do_mes(mov, contas, competencia):
    inicio, fim = _periodo_do_mes(competencia)
    ids = {c['conta_id'] for c in contas if c['analitica'] and c['grupo'] == 'resultado'}
    linhas = {}
    for m in mov:
        if not (inicio <= m['data'] <= fim) or m['conta_id'] not in ids:
            continue
        mov_l = linhas.setdefault(m['conta_id'], {'debito': 0, 'credito': 0})
        mov_l['debito'] += m['debito_centavos']
        mov_l['credito'] += m['credito_centavos']
    receitas = despesas = 0
    detalhes = []
    for c in contas:
        l = linhas.get(c['conta_id'])
        if not l:
            continue
        resultado = l['credito'] - l['debito']
        if resultado >= 0:
            receitas += resultado
        else:
            despesas += -resultado
        detalhes.append({'conta': c['descricao'], 'movimento': resultado,
                         'natureza': 'receita' if resultado >= 0 else 'despesa'})
    detalhes.sort(key=lambda d: -abs(d['movimento']))
    return {'receitas': receitas, 'despesas': despesas,
            'resultado': receitas - despesas, 'detalhes': detalhes}


def _por_natureza(mov, contas, inicio, fim):
    """Total do mês por natureza (ativo/passivo/receita/despesa/ajuste), para comparação."""
    ids_natureza = {c['conta_id']: c.get('natureza') for c in contas if c['analitica']}
    totais = defaultdict_(int)
    for m in mov:
        if not (inicio <= m['data'] <= fim):
            continue
        nat = ids_natureza.get(m['conta_id'])
        if nat:
            totais[nat] += m['debito_centavos'] - m['credito_centavos']
    return totais


def defaultdict_(tipo):
    from collections import defaultdict
    return defaultdict(tipo)


@bp.route('', methods=['GET', 'POST'])
@login_required
def relatorio():
    from modules.pages import NAV
    mov = fetch('SELECT data, conta_id, debito_centavos, credito_centavos '
                'FROM lancamentos ORDER BY data')
    contas = fetch('SELECT conta_id, descricao, analitica, grupo, componente, natureza FROM contas')
    competencia = (request.form.get('competencia') or '').strip() \
        if request.method == 'POST' else ''
    if len(competencia) != 7 or not competencia[:4].isdigit() or not competencia[5:7].isdigit():
        competencia = _competencia_padrao(mov)
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    inicio, fim = _periodo_do_mes(competencia)
    fim_anterior = date(ano, mes, 1) - __import__('datetime').timedelta(days=1)

    resultado = _resultado_do_mes(mov, contas, competencia)
    ativos = {c['conta_id'] for c in contas if c['analitica'] and c.get('componente') == 'caixa'}
    caixa_fim = _fechamento(mov, ativos, fim.isoformat())
    caixa_antes = _fechamento(mov, ativos, fim_anterior.isoformat())
    variacao = caixa_fim - caixa_antes

    caixa_d, caixa_c = 0, 0
    for m in mov:
        if inicio <= m['data'] <= fim and m['conta_id'] in ativos:
            caixa_d += m['debito_centavos']
            caixa_c += m['credito_centavos']

    destaques = variacoes_conta(mov, contas) + caixa_destaque(mov, contas)

    cfg = _cfg_da_ia()
    modo = 'nvidia' if cfg else 'local'
    narrativa = None
    aviso = None
    if request.method == 'POST' and mov:
        dados = {
            'competencia': competencia,
            'receitas': resultado['receitas'],
            'despesas': resultado['despesas'],
            'resultado': resultado['resultado'],
            'margem': (resultado['resultado'] / resultado['receitas'] * 100) if resultado['receitas'] else None,
            'caixa_final': caixa_fim,
            'variacao_caixa': variacao,
            'destaques': destaques,
            'top_movimentos': resultado['detalhes'][:8],
        }
        pergunta = (request.form.get('foco') or '').strip()
        resposta, modo_resp, _ = chat_da_analise(dados, pergunta)
        narrativa = resposta
        if modo_resp == 'local':
            aviso = frase_hibrida((cfg or {}).get('modelo', MODELO_PADRAO))
    return render_template('relatorio_mensal.html', nav=NAV, mov=len(mov),
                           competencia=competencia, resultado=resultado,
                           caixa_fim=caixa_fim, caixa_antes=caixa_antes,
                           variacao=variacao, caixa_d=caixa_d, caixa_c=caixa_c,
                           destaques=destaques, narrativa=esclarecer(narrativa),
                           aviso=esclarecer(aviso), modo=modo)


def _cfg_da_ia():
    """Configuração vigente (tabela oficial da instância); None quando sem chave."""
    linhas = fetch('SELECT chave, modelo FROM configuracoes_ia WHERE id=1')
    return linhas[0] if linhas else None
