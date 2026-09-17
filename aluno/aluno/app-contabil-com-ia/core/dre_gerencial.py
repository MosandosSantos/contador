"""Cálculo puro da DRE gerencial; valores sempre em centavos."""
import calendar
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from core.estrutura_dre import SEM_REGRA
from core.dre_hierarquia import reagrupar_arvore


def _data(valor):
    return valor.isoformat() if hasattr(valor, 'isoformat') else str(valor)


def _valor(movimento):
    return int(movimento['debito_centavos']) - int(movimento['credito_centavos'])


def _ordem_conta(conta):
    try:
        ordem = int(conta.get('ordem') or 100)
    except (TypeError, ValueError):
        ordem = 100
    return ordem, str(conta['conta_id'])


def _pais_contas(contas):
    """Árvore apenas dos nós existentes; legado usa máscaras 1/2/3/5."""
    por_id = {str(conta['conta_id']): conta for conta in contas}
    pais = {}
    for conta_id, conta in por_id.items():
        pai = str(conta.get('conta_pai_id') or '')
        if pai in por_id and pai != conta_id:
            pais[conta_id] = pai
            continue
        candidatos = [conta_id[:n] for n in (5, 3, 2, 1) if n < len(conta_id)]
        existente = next((codigo for codigo in candidatos if codigo in por_id), '')
        if existente:
            pais[conta_id] = existente
    return pais


def _resolver_vinculo(vinculos, grupos):
    codigos = {str(grupo['codigo']) for grupo in grupos}
    por_conta = defaultdict(dict)
    for vinculo in vinculos:
        codigo = str(vinculo['grupo_codigo'])
        if codigo in codigos:
            por_conta[str(vinculo['conta_id'])][str(vinculo.get('centro_id') or '')] = codigo
    return por_conta


def calcular(mov, contas, grupos, vinculos, inicio, fim):
    """Retorna linhas, total e não classificadas sem duplicar subtotais."""
    inicio, fim = str(inicio), str(fim)
    mapa_contas = {str(c['conta_id']): c for c in contas}
    grupos_ordenados = sorted(grupos, key=lambda g: (int(g['ordem']), str(g['codigo'])))
    por_conta = _resolver_vinculo(vinculos, grupos_ordenados)
    valores, nao_classificadas = defaultdict(int), defaultdict(int)
    total = 0
    tem_movimentos = False
    for movimento in mov:
        data = _data(movimento['data'])
        if not inicio <= data <= fim or movimento.get('tipo') == 'encerramento':
            continue
        conta_id = str(movimento['conta_id'])
        if mapa_contas.get(conta_id, {}).get('grupo') != 'resultado':
            continue
        tem_movimentos = True
        valor = -_valor(movimento)  # crédito aumenta o resultado
        total += valor
        centro = str(movimento.get('centro_id') or '')
        vinculos_conta = por_conta.get(conta_id, {})
        codigo = vinculos_conta.get(centro, vinculos_conta.get(''))
        if codigo:
            valores[codigo] += valor
        else:
            nao_classificadas[(conta_id, centro)] += valor
            if any(g['codigo'] == SEM_REGRA for g in grupos_ordenados):
                valores[SEM_REGRA] += valor

    linhas, acumulado_detalhes = [], 0
    for grupo in grupos_ordenados:
        codigo, tipo = str(grupo['codigo']), str(grupo['tipo'])
        if tipo == 'detalhe':
            valor = valores[codigo]
            acumulado_detalhes += valor
        else:
            valor = acumulado_detalhes
        linhas.append({'codigo': codigo, 'nome': grupo['nome'], 'ordem': int(grupo['ordem']), 'tipo': tipo, 'valor_centavos': valor})
    nao = [
        {'conta_id': conta_id, 'centro_id': centro_id, 'valor_centavos': valor}
        for (conta_id, centro_id), valor in sorted(nao_classificadas.items()) if valor
    ]
    return {'linhas': linhas, 'total': total, 'nao_classificadas': nao, 'tem_movimentos': tem_movimentos}


def _av(valor, base):
    return None if valor is None or base in (None, 0) else valor * 100 / base


def _arvore(mov, contas, grupos, vinculos, periodos, anteriores, atuais, anteriores_calc, base_av, niveis=None, centros=None):
    """Árvore grupo -> caminho de contas existente -> centro real.

    As contas são agregadas diretamente de cada lançamento classificado. Um
    subtotal permanece uma folha: ele reproduz a linha contábil e não entra na
    soma dos seus grupos anteriores pela árvore.
    """
    grupos_ordenados = sorted(grupos, key=lambda g: (int(g['ordem']), str(g['codigo'])))
    grupos_por_codigo = {str(grupo['codigo']): grupo for grupo in grupos_ordenados}
    por_id = {str(conta['conta_id']): conta for conta in contas}
    pais, por_conta = _pais_contas(contas), _resolver_vinculo(vinculos, grupos)
    meses_atuais, meses_anteriores = set(periodos), set(anteriores)
    def caminho(conta_id):
        itens, visitadas, atual = [], set(), conta_id
        while atual and atual not in visitadas and atual in por_id:
            visitadas.add(atual)
            itens.append(atual)
            atual = pais.get(atual, '')
        return list(reversed(itens))

    contribuicoes = {}

    def adicionar(movimento, periodo, anterior=False):
        conta_id = str(movimento['conta_id'])
        conta = por_id.get(conta_id)
        if not conta or conta.get('grupo') != 'resultado' or movimento.get('tipo') == 'encerramento':
            return
        centro = str(movimento.get('centro_id') or '')
        regras = por_conta.get(conta_id, {})
        codigo_grupo = regras.get(centro, regras.get(''))
        if not codigo_grupo and SEM_REGRA in grupos_por_codigo:
            codigo_grupo = SEM_REGRA
        grupo = grupos_por_codigo.get(codigo_grupo)
        if not grupo or grupo['tipo'] != 'detalhe':
            return
        caminho_contas = caminho(conta_id)
        chave = (codigo_grupo, tuple(caminho_contas), centro)
        contribuicao = contribuicoes.setdefault(chave, {
            'grupo_codigo': codigo_grupo, 'contas': [por_id[codigo] for codigo in caminho_contas],
            'centro_id': centro, 'valores': {p: None for p in periodos}, 'ano_anterior_centavos': None,
        })
        valor = -_valor(movimento)
        if anterior:
            contribuicao['ano_anterior_centavos'] = (contribuicao['ano_anterior_centavos'] or 0) + valor
        else:
            contribuicao['valores'][periodo] = (contribuicao['valores'][periodo] or 0) + valor

    for movimento in mov:
        periodo = _data(movimento['data'])[:7]
        if periodo in meses_atuais:
            adicionar(movimento, periodo)
        elif periodo in meses_anteriores:
            adicionar(movimento, periodo, anterior=True)

    linhas_por_periodo = {p: {x['codigo']: x for x in resultado['linhas']} for p, resultado in atuais.items()}
    anteriores_por_periodo = {p: {x['codigo']: x for x in resultado['linhas']} for p, resultado in anteriores_calc.items()}
    bases = {p: linhas_por_periodo[p][base_av]['valor_centavos'] if base_av in linhas_por_periodo[p] and atuais[p]['tem_movimentos'] else None for p in periodos}
    base_acumulada = sum(v for v in bases.values() if v is not None) if any(v is not None for v in bases.values()) else None
    arvore_linhas = reagrupar_arvore(grupos_ordenados, contribuicoes.values(), periodos, niveis=niveis, centros=centros)
    por_node_id = {node['node_id']: node for node in arvore_linhas}
    for grupo in grupos_ordenados:
        codigo, node = str(grupo['codigo']), por_node_id[f"grupo:{grupo['codigo']}"]
        node['valores'] = {p: linhas_por_periodo[p][codigo]['valor_centavos'] if atuais[p]['tem_movimentos'] else None for p in periodos}
        anteriores_grupo = [anteriores_por_periodo[p][codigo]['valor_centavos'] for p in anteriores if anteriores_calc[p]['tem_movimentos']]
        node['ano_anterior_centavos'] = sum(anteriores_grupo) if anteriores_grupo else None

    base_anterior = por_node_id.get(f'grupo:{base_av}', {}).get('ano_anterior_centavos')
    resultado = []
    for node in arvore_linhas:
        acumulado = sum(v for v in node['valores'].values() if v is not None) if any(v is not None for v in node['valores'].values()) else None
        node['acumulado_centavos'] = acumulado
        node['av_valores'] = {periodo: _av(node['valores'][periodo], bases[periodo]) for periodo in periodos}
        node['av_percentual'] = _av(acumulado, base_acumulada)
        node['av_ano_anterior_percentual'] = _av(node['ano_anterior_centavos'], base_anterior)
        resultado.append(node)
    return {'linhas': resultado, 'base_av_codigo': base_av, 'base_av_centavos': base_acumulada, 'base_av_ano_anterior_centavos': base_anterior}


def quadro_mensal(mov, contas, grupos, vinculos, competencia, base_av='receita_liquida', niveis=None, centros=None):
    """Monta Jan..competência, acumulado, anterior, AV e árvore detalhada."""
    if not re.fullmatch(r'(?:1\d{3}|2\d{3})-(0[1-9]|1[0-2])', competencia):
        raise ValueError('Competência inválida.')
    ano, ultimo_mes = map(int, competencia.split('-'))
    periodos = [f'{ano}-{mes:02}' for mes in range(1, ultimo_mes + 1)]
    anteriores = [f'{ano - 1}-{mes:02}' for mes in range(1, ultimo_mes + 1)]

    def fechar(periodo):
        y, m = map(int, periodo.split('-'))
        return calcular(mov, contas, grupos, vinculos, f'{periodo}-01', f'{periodo}-{calendar.monthrange(y, m)[1]:02}')

    atuais = {periodo: fechar(periodo) for periodo in periodos}
    anteriores_calc = {periodo: fechar(periodo) for periodo in anteriores}
    grupos_ordenados = sorted(grupos, key=lambda g: (int(g['ordem']), str(g['codigo'])))
    grupos_por_codigo = {str(grupo['codigo']): grupo for grupo in grupos_ordenados}
    # Compatibilidade com o quadro anterior: receita_liquida era uma chave
    # implícita e podia não existir no cadastro. A UI só oferece subtotais.
    if base_av and base_av != 'receita_liquida' and (base_av not in grupos_por_codigo or grupos_por_codigo[base_av]['tipo'] != 'subtotal'):
        raise ValueError('Base de AV deve ser um subtotal cadastrado.')
    por_codigo_atual = {p: {x['codigo']: x for x in r['linhas']} for p, r in atuais.items()}
    por_codigo_anterior = {p: {x['codigo']: x for x in r['linhas']} for p, r in anteriores_calc.items()}
    linhas = []
    for grupo in grupos_ordenados:
        codigo = str(grupo['codigo'])
        valores = {p: por_codigo_atual[p][codigo]['valor_centavos'] if atuais[p]['tem_movimentos'] else None for p in periodos}
        valores_anterior = {p: por_codigo_anterior[p][codigo]['valor_centavos'] if anteriores_calc[p]['tem_movimentos'] else None for p in anteriores}
        acumulado = sum(v for v in valores.values() if v is not None) if any(v is not None for v in valores.values()) else None
        ano_anterior = sum(v for v in valores_anterior.values() if v is not None) if any(v is not None for v in valores_anterior.values()) else None
        linhas.append({'codigo': codigo, 'nome': grupo['nome'], 'ordem': int(grupo['ordem']), 'tipo': grupo['tipo'], 'valores': valores, 'acumulado_centavos': acumulado, 'ano_anterior_centavos': ano_anterior})
    base_valores = next((x['valores'] for x in linhas if x['codigo'] == base_av), {periodo: None for periodo in periodos})
    receita = sum(v for v in base_valores.values() if v is not None) if any(v is not None for v in base_valores.values()) else None
    base_anterior = next((x['ano_anterior_centavos'] for x in linhas if x['codigo'] == base_av), None)
    for linha in linhas:
        linha['av_valores'] = {periodo: _av(linha['valores'][periodo], base_valores[periodo]) for periodo in periodos}
        linha['av_percentual'] = _av(linha['acumulado_centavos'], receita)
        linha['av_ano_anterior_percentual'] = _av(linha['ano_anterior_centavos'], base_anterior)
    nao = []
    chaves_nao = set().union(*(set((x['conta_id'], x['centro_id']) for x in r['nao_classificadas']) for r in atuais.values()))
    for conta_id, centro_id in sorted(chaves_nao):
        valores = {}
        for periodo, resultado in atuais.items():
            achado = next((x['valor_centavos'] for x in resultado['nao_classificadas'] if x['conta_id'] == conta_id and x['centro_id'] == centro_id), 0)
            valores[periodo] = achado if resultado['tem_movimentos'] else None
        acumulado = sum(v for v in valores.values() if v is not None) if any(v is not None for v in valores.values()) else None
        nao.append({'conta_id': conta_id, 'centro_id': centro_id, 'valores': valores, 'acumulado_centavos': acumulado, 'av_valores': {periodo: _av(valores[periodo], base_valores[periodo]) for periodo in periodos}, 'av_percentual': _av(acumulado, receita)})
    total_atual = sum(r['total'] for r in atuais.values()) if any(r['tem_movimentos'] for r in atuais.values()) else None
    total_anterior = sum(r['total'] for r in anteriores_calc.values()) if any(r['tem_movimentos'] for r in anteriores_calc.values()) else None
    return {'periodos': periodos, 'linhas': linhas, 'total_centavos': total_atual, 'ano_anterior_centavos': total_anterior, 'nao_classificadas': nao, 'receita_liquida_centavos': receita, 'base_av_codigo': base_av, 'arvore': _arvore(mov, contas, grupos_ordenados, vinculos, periodos, anteriores, atuais, anteriores_calc, base_av, niveis=niveis, centros=centros)}


def agrupar_trimestres(quadro):
    """Agrupa um quadro mensal pronto sem perder ausências ou AV."""
    periodos = quadro['periodos']
    faixas = [(f'{((indice // 3) + 1)}º tri', periodos[indice:indice + 3]) for indice in range(0, len(periodos), 3)]

    def consolidar(valores):
        return {rotulo: sum(v for p in meses if (v := valores[p]) is not None) if any(valores[p] is not None for p in meses) else None for rotulo, meses in faixas}

    linhas = [dict(linha, valores=consolidar(linha['valores'])) for linha in quadro['linhas']]
    nao = [dict(linha, valores=consolidar(linha['valores'])) for linha in quadro['nao_classificadas']]
    arvore = dict(quadro['arvore'])
    arvore_linhas = [dict(linha, valores=consolidar(linha['valores'])) for linha in arvore['linhas']]
    base = next((linha['valores'] for linha in arvore_linhas if linha['node_id'] == f"grupo:{arvore['base_av_codigo']}"), {})
    for linha in linhas + nao + arvore_linhas:
        linha['av_valores'] = {rotulo: _av(linha['valores'][rotulo], base.get(rotulo)) for rotulo, _ in faixas}
    arvore['linhas'] = arvore_linhas
    saida = dict(quadro, periodos=[rotulo for rotulo, _ in faixas], linhas=linhas, nao_classificadas=nao, arvore=arvore)
    if 'origens' in quadro:
        saida['origens'] = {}
        for rotulo, meses in faixas:
            origens = {quadro['origens'][mes] for mes in meses}
            saida['origens'][rotulo] = next(iter(origens)) if len(origens) == 1 else 'misto'
    return saida


def quadro_projetado(mov, orcamento, contas, grupos, vinculos, ano, corte, base_av='receita_liquida', niveis=None, centros=None):
    """Ano completo: realizado <= corte global; orçamento somente depois dele.

    O orçamento é adaptado em memória para o mesmo cálculo de grupos/árvore.
    Não vira escrituração, não é replicado por centros, nem preenche lacunas
    anteriores ao corte. O comparativo anterior contém somente realizado.
    """
    ano = int(ano)
    if not 1000 <= ano <= 2999 or not re.fullmatch(r'(?:1\d{3}|2\d{3})-(0[1-9]|1[0-2])', corte):
        raise ValueError('Ano ou corte inválido.')
    periodos = [f'{ano}-{mes:02}' for mes in range(1, 13)]
    atuais = set(periodos)
    resultado = {str(c['conta_id']) for c in contas if c.get('grupo') == 'resultado' and c.get('analitica', True)}
    combinados = [dict(m) for m in mov if _data(m['data'])[:7] <= corte and _data(m['data'])[:4] in (str(ano-1), str(ano))]
    meses_orcados = set()
    for item in orcamento:
        periodo, conta = str(item['competencia']), str(item['conta_id'])
        if periodo not in atuais or periodo <= corte or conta not in resultado:
            continue
        valor = int(item['valor_dc_centavos'])
        combinados.append({'data': periodo+'-01', 'conta_id': conta, 'centro_id': '',
                           'debito_centavos': max(valor, 0), 'credito_centavos': max(-valor, 0), 'tipo': 'orcamento'})
        meses_orcados.add(periodo)
    quadro = quadro_mensal(combinados, contas, grupos, vinculos, f'{ano}-12', base_av, niveis=niveis, centros=centros)
    quadro.update(ano=ano, corte=corte, tem_orcado=any(p > corte for p in periodos),
                  origens={p: 'realizado' if p <= corte else 'orcado' for p in periodos},
                  meses_sem_orcamento=[p for p in periodos if p > corte and p not in meses_orcados])
    return quadro


def formatar_valor(valor, mil=False, centavos=False):
    """Só apresentação; cálculo e AV conservam os centavos inteiros."""
    if valor is None:
        return '—'
    numero = (Decimal(int(valor)) / (100000 if mil else 100)).quantize(Decimal('0.01' if centavos else '1'), rounding=ROUND_HALF_UP)
    texto = format(abs(numero), ',.2f' if centavos else ',.0f').replace(',', '_').replace('.', ',').replace('_', '.')
    return f'({texto})' if numero < 0 else texto
