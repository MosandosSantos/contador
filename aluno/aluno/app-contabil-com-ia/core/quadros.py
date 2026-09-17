"""Quadros estruturados para a UI, derivados do mesmo motor contábil.

DFC é uma visão de movimentos de caixa classificados; não substitui uma DFC
completa enquanto não houver a política contábil para todas as rubricas.
"""
from collections import defaultdict

from core.calculos import componentes_pl, demonstrativo, limites, valor

CANONICA = [
    ('receita_bruta', 'Receita bruta', 'detalhe'), ('deducoes', 'Deduções', 'detalhe'),
    ('receita_liquida', 'Receita líquida', 'subtotal'), ('custos_servicos', 'Custos dos serviços', 'detalhe'),
    ('lucro_bruto', 'Lucro bruto', 'subtotal'), ('pessoal', 'Pessoal', 'detalhe'),
    ('estrutura', 'Estrutura', 'detalhe'), ('outras_linhas', 'Outras linhas', 'detalhe'),
    ('ebitda', 'EBITDA', 'subtotal'), ('depreciacao', 'Depreciação', 'detalhe'),
    ('ebit', 'EBIT', 'subtotal'), ('financeiro', 'Resultado financeiro', 'detalhe'),
    ('tributos_resultado', 'Tributos sobre resultado', 'detalhe'), ('resultado', 'Resultado do período', 'subtotal'),
]
DERIVADAS = {'receita_liquida', 'lucro_bruto', 'ebitda', 'ebit', 'resultado'}
CLASSES = {'circulante':'Circulante','nao_circulante':'Não circulante','ativo': 'Ativo', 'ativo_circulante': 'Ativo circulante', 'ativo_nao_circulante': 'Ativo não circulante', 'passivo': 'Passivo', 'passivo_circulante': 'Passivo circulante', 'passivo_nao_circulante': 'Passivo não circulante', 'pl': 'Patrimônio líquido','pendente':'A classificar'}


def _meses(competencia):
    ano, mes = map(int, competencia.split('-'))
    return [f'{ano}-{n:02}' for n in range(1, mes + 1)]


def _anterior_mes(competencia):
    ano, mes = map(int, competencia.split('-'))
    if ano == 1900 and mes == 1: return None
    return f'{ano - 1}-12' if mes == 1 else f'{ano}-{mes - 1:02}'


def _dre_mes(mov, contas, competencia):
    """None significa mês sem fato de resultado, inclusive se houver abertura."""
    linhas = demonstrativo(mov, contas, competencia, 'mensal')['dre']['linhas_centavos']
    return linhas if linhas else None


def _somar(valores):
    presentes = [x for x in valores if x is not None]
    return sum(presentes) if presentes else None


def _valor_linha(linhas, chave):
    if linhas is None: return None
    if chave == 'receita_liquida': return linhas.get('receita_bruta', 0) + linhas.get('deducoes', 0)
    if chave == 'lucro_bruto': return _valor_linha(linhas, 'receita_liquida') + linhas.get('custos_servicos', 0)
    if chave == 'ebitda': return _valor_linha(linhas, 'lucro_bruto') + linhas.get('pessoal', 0) + linhas.get('estrutura', 0) + linhas.get('outras_linhas', 0)
    if chave == 'ebit': return _valor_linha(linhas, 'ebitda') + linhas.get('depreciacao', 0)
    if chave == 'resultado':
        return sum(v for k, v in linhas.items() if k in {'receita_bruta', 'deducoes', 'custos_servicos', 'pessoal', 'estrutura', 'outras_linhas', 'depreciacao', 'financeiro', 'tributos_resultado'})
    return linhas.get(chave, 0)


def _balanco_lados(mov, contas, competencia, alcance, *, saldos_atual=None, saldos_anterior=None):
    from core.arvore import linearizar,com_ancestrais
    arvore=linearizar(contas)
    indice={c['node_id']:c for c in arvore}
    atual=saldos_atual if saldos_atual is not None else demonstrativo(mov,contas,competencia,alcance)['balanco']
    anterior_comp=_anterior_mes(competencia)
    anterior=saldos_anterior if saldos_anterior is not None else (demonstrativo(mov,contas,anterior_comp,alcance)['balanco'] if anterior_comp else {'saldos_dc_por_conta':{},'componentes_pl':{}})

    def lado(titulo,grupos):
        folhas=[c['node_id'] for c in arvore if c.get('analitica') is not False and c.get('grupo') in grupos]
        nos=com_ancestrais(arvore,[c['node_id'] for c in arvore if c.get('grupo') in grupos])
        ids={c['node_id'] for c in nos}
        filhos=defaultdict(list)
        for c in nos:filhos[c['parent_id'] if c['parent_id'] in ids else ''].append(c['node_id'])
        # Resultado não encerrado é uma linha derivada no ancestral comum do PL.
        # Nunca é gravado como lançamento nem duplicado nos totais.
        alvo_pl=''
        if 'pl' in grupos:
            caminhos=[]
            for codigo in folhas:
                if indice[codigo].get('grupo')!='pl':continue
                ancestrais=set();pai=indice[codigo]['parent_id']
                while pai:
                    ancestrais.add(pai);pai=indice[pai]['parent_id']
                caminhos.append(ancestrais)
            comuns=set.intersection(*caminhos) if caminhos else set()
            if comuns:alvo_pl=max(comuns,key=lambda x:indice[x]['level'])
            filhos[alvo_pl].append('__resultado_pl__')

        def saldo(codigo,balanco):
            if codigo=='__resultado_pl__':return balanco['componentes_pl'].get('resultado_corrente',0)
            if filhos[codigo]:return sum(saldo(filho,balanco) for filho in filhos[codigo])
            if codigo not in folhas:return 0
            bruto=balanco['saldos_dc_por_conta'].get(codigo,0)
            return bruto if indice[codigo].get('grupo')=='ativo' else -bruto

        linhas=[]
        def adicionar(codigo,nivel=0,pai=''):
            derivado=codigo=='__resultado_pl__'
            c=indice.get(codigo,{})
            linhas.append({'nome':'Resultado ainda não encerrado' if derivado else c.get('descricao',codigo),
                           'tipo':'derivado' if derivado else 'sintetica' if c.get('analitica') is False else 'analitica',
                           'atual':saldo(codigo,atual),'anterior':saldo(codigo,anterior),
                           'conta_id':None if derivado else codigo,'nivel':nivel,'classe_bp':c.get('classe_bp'),
                           'node_id':codigo,'parent_id':pai,'level':nivel,'has_children':bool(filhos[codigo])})
            for filho in filhos[codigo]:adicionar(filho,nivel+1,codigo)
        roots=filhos[''][:]
        for codigo in roots:adicionar(codigo)
        return {'titulo':titulo,'linhas':linhas,'total':sum(saldo(x,atual) for x in roots),'anterior':sum(saldo(x,anterior) for x in roots)}
    return [lado('Ativo',{'ativo'}),lado('Passivo e patrimônio líquido',{'passivo','pl'})]


def _dfc_linhas(mov, contas, meses):
    """Agrupa cada movimento de caixa uma vez: atividade, depois suas rubricas."""
    caixa = {x['conta_id'] for x in contas if x.get('componente') == 'caixa'}; indice = {mes: n for n, mes in enumerate(meses)}
    atividades = defaultdict(lambda: defaultdict(lambda: [0] * len(meses)))
    for x in mov:
        mes = x['data'][:7]
        if x['conta_id'] not in caixa or mes not in indice or x.get('tipo') == 'abertura': continue
        atividade = x.get('atividade_caixa') if x.get('atividade_caixa') in ('operacional', 'investimento', 'financiamento') else 'não_classificado'
        rubrica = x.get('rubrica_caixa') or 'não_classificado'
        atividades[atividade][rubrica][indice[mes]] += valor(x)
    linhas = []
    for atividade in sorted(atividades):
        rubricas = atividades[atividade]; subtotal = [sum(valores[n] for valores in rubricas.values()) for n in range(len(meses))]
        linhas.append({'nome': atividade, 'tipo': 'atividade', 'valores': subtotal, 'acumulado': sum(subtotal)})
        for rubrica in sorted(rubricas):
            valores = rubricas[rubrica]; linhas.append({'nome': rubrica, 'tipo': 'rubrica', 'atividade': atividade, 'valores': valores, 'acumulado': sum(valores)})
    return linhas


def construir(mov, contas, competencia, alcance='mensal'):
    inicio, fim = limites(competencia, alcance); meses = _meses(competencia)
    mensais = [_dre_mes(mov, contas, mes) for mes in meses]
    conhecidas = {x[0] for x in CANONICA if x[0] not in DERIVADAS | {'outras_linhas'}}
    desconhecidas = set().union(*(set(x or {}) for x in mensais)) - conhecidas
    if desconhecidas:
        for linhas in mensais:
            if linhas is not None: linhas['outras_linhas'] = sum(linhas.pop(x, 0) for x in desconhecidas)
    ano = int(competencia[:4]); anterior_comp = None if ano == 1900 else f'{ano - 1}-{competencia[5:]}'
    anterior = (demonstrativo(mov, contas, anterior_comp, 'acumulado')['dre']['linhas_centavos'] or None) if anterior_comp else None
    if anterior is not None and desconhecidas:
        anterior = dict(anterior); anterior['outras_linhas'] = sum(anterior.pop(x, 0) for x in desconhecidas)
    dre_linhas = []
    for chave, nome, tipo in CANONICA:
        if chave == 'outras_linhas' and not desconhecidas: continue
        valores = [_valor_linha(linhas, chave) for linhas in mensais]
        dre_linhas.append({'nome': nome, 'tipo': tipo, 'valores': valores, 'acumulado': _somar(valores), 'anterior': _valor_linha(anterior, chave)})
    dfc_linhas = _dfc_linhas(mov, contas, meses)
    demonstrativo_atual = demonstrativo(mov, contas, competencia, alcance)
    primeiro = demonstrativo(mov, contas, meses[0], 'mensal')['dfc']['caixa_inicial_centavos']; ultimo = demonstrativo(mov, contas, competencia, 'mensal')['dfc']['caixa_final_centavos']; variacao = ultimo - primeiro
    dfc_linhas.extend([{'nome': 'Caixa inicial', 'tipo': 'caixa_inicial', 'valores': [primeiro] + [None] * (len(meses) - 1), 'acumulado': primeiro}, {'nome': 'Variação de caixa', 'tipo': 'caixa_variacao', 'valores': [None] * (len(meses) - 1) + [variacao], 'acumulado': variacao}, {'nome': 'Caixa final', 'tipo': 'caixa_final', 'valores': [None] * (len(meses) - 1) + [ultimo], 'acumulado': ultimo}])
    dmpl_linhas = [{'nome': 'Saldo inicial', 'tipo': 'saldo_inicial', 'componentes': demonstrativo_atual['dmpl']['inicio'], 'total': sum(demonstrativo_atual['dmpl']['inicio'].values())}]
    for nome, valores in demonstrativo_atual['dmpl']['movimentos'].items(): dmpl_linhas.append({'nome': nome, 'tipo': 'movimento', 'componentes': valores, 'total': sum(valores.values())})
    dmpl_linhas.append({'nome': 'Saldo final', 'tipo': 'saldo_final', 'componentes': demonstrativo_atual['dmpl']['fim'], 'total': sum(demonstrativo_atual['dmpl']['fim'].values())})
    return {'periodo': {'competencia': competencia, 'alcance': alcance, 'inicio': inicio, 'fim': fim}, 'meses': meses, 'balanco_lados': _balanco_lados(mov, contas, competencia, alcance), 'dre_linhas': dre_linhas, 'dfc_linhas': dfc_linhas, 'dmpl_linhas': dmpl_linhas, 'componentes_pl': componentes_pl(contas)}
