"""Balancete por intervalo e saldos históricos no fim de cada mês, em centavos."""
import calendar
import re
from collections import defaultdict
from datetime import date

from core.arvore import linearizar
from core.dre_hierarquia import normalizar_niveis, reagrupar_arvore


def intervalo(data_de, data_ate):
    try:
        if any(not isinstance(s, str) or not re.fullmatch(r'(19\d{2}|20\d{2}|21\d{2})-\d{2}-\d{2}', s) for s in (data_de, data_ate)):
            raise ValueError()
        inicio, fim = date.fromisoformat(data_de), date.fromisoformat(data_ate)
    except ValueError:
        raise ValueError('Informe Data De e Data Até válidas, entre 1900 e 2199.') from None
    if inicio > fim:
        raise ValueError('Data De deve ser anterior ou igual à Data Até.')
    return inicio.isoformat(), fim.isoformat()


def fins_de_mes(data_de, data_ate):
    inicio, fim = intervalo(data_de, data_ate)
    ano, mes = map(int, inicio[:7].split('-'))
    resultado = []
    while f'{ano:04}-{mes:02}' <= fim[:7]:
        resultado.append(f'{ano:04}-{mes:02}-{calendar.monthrange(ano, mes)[1]:02}')
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return resultado


def opcoes_niveis(contas):
    return [{'chave': f'conta:{n}', 'nome': f'Nível {n} da conta'} for n in sorted({c['nivel'] for c in linearizar(contas)})] + [{'chave': 'centro', 'nome': 'Centro de custo'}]


def validar_niveis(niveis, contas):
    niveis = normalizar_niveis(niveis)
    permitidos = {o['chave'] for o in opcoes_niveis(contas)}
    if niveis is None or any(n not in permitidos for n in niveis):
        raise ValueError('Selecione níveis existentes, sem repetir, na ordem desejada.')
    return niveis


def construir(movimentos, contas, data_de, data_ate, tipo='mensal', niveis=None, centros=None):
    inicio, fim = intervalo(data_de, data_ate)
    if tipo not in ('mensal', 'mes-a-mes'):
        raise ValueError('Tipo deve ser Do Mês ou Mês a mês.')
    arvore = linearizar(contas)
    indice = {c['conta_id']: c for c in arvore}
    selecionados = validar_niveis(niveis, contas) if niveis is not None else [o['chave'] for o in opcoes_niveis(contas) if o['chave'] != 'centro']
    meses = fins_de_mes(inicio, fim) if tipo == 'mes-a-mes' else []
    colunas = ([{'chave': m, 'nome': f'{m[5:7]}/{m[:4]}', 'corte': m} for m in meses] if meses else
               [{'chave': k, 'nome': n} for k, n in [('inicio','Saldo inicial D–C'),('debitos','Débitos'),('creditos','Créditos'),('fim','Saldo final D–C')]])
    chaves = [c['chave'] for c in colunas]
    fatos = [(str(x['data'])[:10], x) for x in movimentos]
    ultimo = max((d for d, _ in fatos), default='')
    primeiro = min((d for d, _ in fatos), default='')
    disponivel = lambda corte: bool(ultimo) and primeiro[:7] <= corte[:7] <= ultimo[:7]
    acumulado = defaultdict(lambda: {k: (0 if not meses or disponivel(k) else None) for k in chaves})
    for data, x in fatos:
        conta_id = x['conta_id']
        if conta_id not in indice:
            raise ValueError(f'Conta do lançamento não cadastrada: {conta_id}.')
        if indice[conta_id]['has_children']:
            raise ValueError(f'Conta sintética {conta_id} recebeu lançamento.')
        if data > (meses[-1] if meses else fim):
            continue
        valores = acumulado[(conta_id, str(x.get('centro_id') or ''))]
        debito, credito = int(x['debito_centavos']), int(x['credito_centavos'])
        if meses:
            for corte in meses:
                if valores[corte] is not None and data <= corte:
                    valores[corte] += debito - credito
        else:
            if data < inicio:
                valores['inicio'] += debito - credito
            else:
                valores['debitos'] += debito
                valores['creditos'] += credito
            valores['fim'] += debito - credito
    contas_com_valor = {a for a, _ in acumulado}
    for c in arvore:
        if not c['has_children'] and c['conta_id'] not in contas_com_valor:
            acumulado[(c['conta_id'], '')]  # Contas sem movimento continuam na estrutura.
    contribuicoes = []
    for (codigo, centro), valores in acumulado.items():
        caminho = []
        atual = codigo
        while atual:
            caminho.append(indice[atual]); atual = indice[atual]['parent_id']
        contribuicoes.append({'grupo_codigo': 'balancete', 'contas': list(reversed(caminho)), 'centro_id': centro, 'valores': valores})
    # Reuso somente do agrupador de dimensões, sem linhas/fórmulas de DRE.
    linhas = reagrupar_arvore([{'codigo':'balancete','nome':'Total do balancete','ordem':1,'tipo':'detalhe'}], contribuicoes, chaves, selecionados, centros)
    total = {k: (sum(c['valores'][k] or 0 for c in contribuicoes) if any(c['valores'][k] is not None for c in contribuicoes) else None) for k in chaves}
    if selecionados:
        linhas = [x for x in linhas if x['parent_id']]
        for x in linhas:
            x['nivel'] -= 1
            if x['parent_id'] == 'grupo:balancete':
                x['parent_id'] = ''
    else:
        linhas[0]['valores'] = total
    for c in colunas:
        c['disponivel'] = not meses or disponivel(c['chave'])
    return {'linhas': linhas, 'colunas': colunas, 'total': total, 'inicio': inicio, 'fim': fim,
            'ultimo': ultimo, 'tipo': tipo, 'sem_dados': not bool(fatos),
            'futuro': bool(ultimo) and (meses[-1] if meses else fim) > ultimo, 'niveis': selecionados}
