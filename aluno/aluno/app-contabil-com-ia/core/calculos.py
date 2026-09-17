"""Motor determinístico em centavos, sem códigos de conta fixos."""
import calendar
import re
from collections import defaultdict

COMPONENTES = ['capital', 'lucros_acumulados', 'reservas', 'resultado_corrente']
ALCANCES = {'mensal', 'acumulado', 'trimestral', 'anual'}


def valor(x): return x['debito_centavos'] - x['credito_centavos']


def limites(competencia, alcance='mensal'):
    """Aceita competências normais de 1900 a 2199 e delimita o alcance pedido."""
    if not re.fullmatch(r'(19\d{2}|20\d{2}|21\d{2})-(0[1-9]|1[0-2])', competencia): raise ValueError('Competência inválida.')
    if alcance not in ALCANCES: raise ValueError('Alcance inválido.')
    ano, mes = map(int, competencia.split('-'))
    inicio_mes = 1 if alcance in ('acumulado', 'anual') else (((mes - 1) // 3) * 3 + 1 if alcance == 'trimestral' else mes)
    return f'{ano}-{inicio_mes:02}-01', f'{competencia}-{calendar.monthrange(ano, mes)[1]:02}'


def componentes_pl(contas):
    extras = [x.get('componente') or f"pl_{x['conta_id']}" for x in contas if x.get('grupo') == 'pl' and x.get('analitica') is not False]
    return COMPONENTES + [x for x in dict.fromkeys(extras) if x not in COMPONENTES]


def contas_folha(contas):
    pais = {x.get('conta_pai_id') for x in contas if x.get('conta_pai_id')}
    return {x['conta_id'] for x in contas if x.get('analitica') is not False and x['conta_id'] not in pais}


def demonstrativo(mov, contas_lista, competencia, alcance='mensal', reclass=None, *, intervalo_datas=None):
    inicio, fim = limites(competencia, alcance)
    if intervalo_datas is not None:
        from core.balancete import intervalo
        inicio, fim = intervalo(*intervalo_datas)
    contas = {x['conta_id']: x for x in contas_lista}; componentes = componentes_pl(contas_lista)
    atual, antes = defaultdict(int), defaultdict(int)
    for x in mov:
        if x['data'] <= fim: atual[x['conta_id']] += valor(x)
        if x['data'] < inicio: antes[x['conta_id']] += valor(x)
    xs = [x for x in mov if inicio <= x['data'] <= fim]
    def pl(s):
        p = {k: 0 for k in componentes}
        for a, t in contas.items():
            if t.get('grupo') == 'pl' and t.get('analitica') is not False: p[t.get('componente') or f'pl_{a}'] -= s[a]
            elif t.get('grupo') == 'resultado': p['resultado_corrente'] -= s[a]
        return p
    linhas, gerencial = defaultdict(int), defaultdict(int); reclass = reclass or {}
    for x in xs:
        t = contas.get(x['conta_id'])
        if t and t.get('grupo') == 'resultado' and x.get('tipo') != 'encerramento':
            linha = t.get('linha_dre') or 'outras_linhas'; linhas[linha] -= valor(x); gerencial[reclass.get((x['data'][:7], x['conta_id']), linha)] -= valor(x)
    dre = {'linhas_centavos': dict(linhas), 'receita_liquida_centavos': linhas['receita_bruta'] + linhas['deducoes'], 'resultado_centavos': sum(linhas.values())}
    p0, p1 = pl(antes), pl(atual); mutations = defaultdict(lambda: {k: 0 for k in p1})
    fluxo = defaultdict(int, {'operacional': 0, 'investimento': 0, 'financiamento': 0}); rubricas = defaultdict(int)
    caixa = {x['conta_id'] for x in contas_lista if x.get('componente') == 'caixa'}
    for x in xs:
        t = contas.get(x['conta_id'])
        if not t: continue
        if t.get('grupo') in ('pl', 'resultado'):
            tipo = x.get('tipo') if x.get('tipo') in ('aporte', 'distribuicao', 'encerramento', 'reserva') else 'resultado_periodo'
            comp = (t.get('componente') or f"pl_{x['conta_id']}") if t.get('grupo') == 'pl' else 'resultado_corrente'
            mutations[tipo].setdefault(comp, 0); mutations[tipo][comp] -= valor(x)
        if x['conta_id'] in caixa and x.get('tipo') != 'abertura':
            atividade = x.get('atividade_caixa') if x.get('atividade_caixa') in ('operacional', 'investimento', 'financiamento') else 'não_classificado'
            fluxo[atividade] += valor(x); rubricas[x.get('rubrica_caixa') or 'não_classificado'] += valor(x)
    def variacao(componente):
        saldo = lambda s: sum(s[x['conta_id']] for x in contas_lista if x.get('componente') == componente)
        return -(saldo(atual) - saldo(antes))
    # A ponte usa componentes cadastrados; classificações ausentes ficam em zero.
    ponte = {'resultado_centavos': dre['resultado_centavos'], 'depreciacao_centavos': -linhas.get('depreciacao', 0), 'variacao_clientes_centavos': variacao('clientes'), 'variacao_remuneracao_pagar_centavos': variacao('remuneracao'), 'variacao_tributos_pagar_centavos': variacao('tributos')}
    folhas = contas_folha(contas_lista)
    balanco = {'ativo_centavos': sum(atual[a] for a in folhas if contas[a].get('grupo') == 'ativo'), 'passivo_centavos': -sum(atual[a] for a in folhas if contas[a].get('grupo') == 'passivo'), 'pl_centavos': sum(p1.values()), 'componentes_pl': p1, 'saldos_dc_por_conta': dict(atual)}
    filhos = defaultdict(list)
    for conta_id, conta in contas.items():
        pai = conta.get('conta_pai_id')
        if pai in contas:
            filhos[pai].append(conta_id)
    debitos = defaultdict(int)
    creditos = defaultdict(int)
    for x in xs:
        debitos[x['conta_id']] += x['debito_centavos']
        creditos[x['conta_id']] += x['credito_centavos']

    def saldo_agregado(conta_id, campo, trilha=()):
        """Soma descendentes nas contas sintéticas e acusa hierarquia circular."""
        if conta_id in trilha:
            raise ValueError(f'Hierarquia circular de contas: {conta_id}')
        if filhos[conta_id]:
            return sum(saldo_agregado(filho, campo, trilha + (conta_id,)) for filho in filhos[conta_id])
        return {'inicio': antes, 'debitos': debitos, 'creditos': creditos, 'fim': atual}[campo][conta_id]

    balancete = [{'conta_id': a, 'descricao': t.get('descricao', a),
                  'inicio': saldo_agregado(a, 'inicio'), 'debitos': saldo_agregado(a, 'debitos'),
                  'creditos': saldo_agregado(a, 'creditos'), 'fim': saldo_agregado(a, 'fim')}
                 for a, t in contas.items()]
    return {'competencia': competencia, 'alcance': alcance, 'inicio': inicio, 'fim': fim, 'unidade': 'centavos', 'dre': dre, 'gerencial': dict(gerencial), 'balanco': balanco, 'dmpl': {'inicio': p0, 'movimentos': dict(mutations), 'fim': p1}, 'dfc': {'caixa_inicial_centavos': sum(antes[a] for a in caixa), 'rubricas_centavos': dict(rubricas), 'atividades_centavos': dict(fluxo), 'caixa_final_centavos': sum(atual[a] for a in caixa), 'ponte_indireta': ponte, 'operacional_indireto_centavos': sum(ponte.values())}, 'balancete': balancete}


def comparar(mov, contas, orc, ano=None):
    anos = [int(x['data'][:4]) for x in mov] + [int(x['competencia'][:4]) for x in orc]
    ano = max(anos) if ano is None and anos else ano
    if not isinstance(ano, int) or not 1900 <= ano <= 2199: raise ValueError('Ano inválido.')
    por_id = {x['conta_id']: x for x in contas}; rows = []
    for m in range(1, 13):
        comp, anterior = f'{ano}-{m:02}', f'{ano - 1}-{m:02}'
        reais = [x for x in mov if x['data'][:7] == comp and por_id.get(x['conta_id'], {}).get('grupo') == 'resultado' and x.get('tipo') != 'encerramento']
        previos = [x for x in mov if x['data'][:7] == anterior and por_id.get(x['conta_id'], {}).get('grupo') == 'resultado' and x.get('tipo') != 'encerramento']
        budget_rows = [x for x in orc if x['competencia'] == comp]
        real = demonstrativo(mov, contas, comp)['dre']['resultado_centavos'] if reais else None
        prev = demonstrativo(mov, contas, anterior)['dre']['resultado_centavos'] if previos else None
        budget = -sum(x['valor_dc_centavos'] for x in budget_rows) if budget_rows else None
        rows.append({'competencia': comp, 'realizado': real, 'orcado': budget, 'forecast': real if real is not None else budget, 'origem': 'Realizado' if real is not None else ('Orçamento' if budget is not None else 'Sem dados'), 'variacao': real-budget if real is not None and budget is not None else None, 'anterior': prev})
    return rows


def conciliar(interno, extrato):
    a, b = defaultdict(list), defaultdict(list)
    for x in interno: a[x['referencia']].append(x)
    for x in extrato: b[x['referencia']].append(x)
    rows = []
    for ref in sorted(a.keys() | b.keys()):
        ia, eb = a[ref], b[ref]; v1 = ia[0]['valor_centavos'] if len(ia) == 1 else None; v2 = eb[0]['valor_centavos'] if len(eb) == 1 else None
        status = 'Duplicidade' if len(ia) > 1 or len(eb) > 1 else ('Somente no extrato' if not ia else ('Ausente no extrato' if not eb else ('Valor divergente' if v1 != v2 else 'Conciliado')))
        rows.append({'referencia': ref, 'interno': v1, 'extrato': v2, 'diferenca': v2-v1 if v1 is not None and v2 is not None else None, 'status': status, 'quantidade_extrato': len(eb), 'documento': ia[0].get('documento_id', '') if ia else ''})
    return rows
