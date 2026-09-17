"""Destaques automáticos calculados pelo app (R3): variações relevantes.

Tudo é calculado localmente a partir dos lançamentos; a IA nunca inventa estes
números — ela apenas pode explicá-los quando configurada.
"""
from collections import defaultdict


def _fmt(centavos):
    return 'R$ ' + f'{abs(centavos)/100:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def _mes_anterior(competencia):
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    if mes == 1:
        return f'{ano - 1}-12'
    return f'{ano}-{mes - 1:02d}'


def variacoes_conta(mov, contas, grupos=('resultado',), limite=4):
    """Variações mês contra mês por conta analítica dos grupos indicados."""
    ids = {c['conta_id'] for c in contas if c['analitica'] and c['grupo'] in grupos}
    if not ids or not mov:
        return []
    comps = {str(m['data'])[:7] for m in mov}
    ultimo = max(comps)
    anterior = _mes_anterior(ultimo)
    saldos = defaultdict(lambda: defaultdict(int))
    for m in mov:
        comp = str(m['data'])[:7]
        if comp not in (ultimo, anterior) or m['conta_id'] not in ids:
            continue
        saldos[m['conta_id']][comp] += m['debito_centavos'] - m['credito_centavos']
    nomes = {c['conta_id']: c['descricao'] for c in contas}
    achados = []
    for conta_id, por_mes in saldos.items():
        atual = por_mes.get(ultimo, 0)
        antes = por_mes.get(anterior, 0)
        if atual == 0 and antes == 0:
            continue
        diferenca = atual - antes
        if abs(diferenca) < 100_000:
            continue
        pct = (diferenca / abs(antes) * 100) if antes else None
        if pct is not None and abs(pct) < 20:
            continue
        nome = nomes.get(conta_id, conta_id)
        if pct is None:
            texto = (f'{nome}: {_fmt(atual)} em {ultimo} '
                     f'(sem base comparável em {anterior}).')
        else:
            texto = (f'{nome} variou {pct:+.0f}% em {ultimo} contra {anterior}: '
                     f'{_fmt(atual)} após {_fmt(antes)}.')
        achados.append({'titulo': 'Movimento relevante', 'texto': texto, 'forca': abs(diferenca)})
    achados.sort(key=lambda x: -x['forca'])
    for a in achados:
        a.pop('forca', None)
    return achados[:limite]


def caixa_destaque(mov, contas, limite=1):
    """Como o caixa terminou o último mês em relação ao anterior."""
    ids = {c['conta_id'] for c in contas if c['analitica'] and c.get('componente') == 'caixa'}
    if not ids or not mov:
        return []
    comps = {str(m['data'])[:7] for m in mov}
    ultimo = max(comps)
    anterior = _mes_anterior(ultimo)
    def ate(comp):
        return sum(m['debito_centavos'] - m['credito_centavos'] for m in mov
                   if str(m['data'])[:7] <= comp and m['conta_id'] in ids)
    fim, antes = ate(ultimo), ate(anterior)
    diferenca = fim - antes
    if abs(diferenca) < 100_000:
        return []
    sinal = 'aumentou' if diferenca > 0 else 'caiu'
    return [{'titulo': 'Caixa',
             'texto': (f'Saldo de caixa e bancos {sinal} em {_fmt(diferenca)} no mês: '
                       f'{_fmt(fim)} ao final de {ultimo} (antes {_fmt(antes)}).')}]


def destaques(mov, contas, limite=4):
    """Lista combinada de destaques para a página inicial."""
    if not mov:
        return []
    achados = caixa_destaque(mov, contas) + variacoes_conta(mov, contas)
    return achados[:limite]
