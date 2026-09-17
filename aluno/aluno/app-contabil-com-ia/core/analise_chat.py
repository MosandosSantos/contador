"""Séries financeiras determinísticas para a conversa de análise.

Este módulo recebe fatos já importados e nunca consulta banco nem usa data do
computador.  Valores monetários são sempre centavos; apenas liquidez é índice.
"""
from __future__ import annotations

import calendar
from datetime import date

from core.calculos import contas_folha, demonstrativo
from core.quadros import _valor_linha


METRICAS = {
    'liquidez_corrente': ('Liquidez corrente', 'indice'),
    'faturamento': ('Faturamento', 'centavos'),
    'receita_liquida': ('Receita líquida', 'centavos'),
    'resultado': ('Resultado do período', 'centavos'),
    'ebitda': ('EBITDA', 'centavos'),
}
PERIODICIDADES = {'mensal', 'trimestral'}


def _data(valor):
    if valor is None:
        return ''
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)[:10]


def _ultimo_ano(ultimo):
    if ultimo is None:
        return None
    if isinstance(ultimo, int) and not isinstance(ultimo, bool):
        return ultimo
    texto = _data(ultimo)
    try:
        return date.fromisoformat(texto).year
    except ValueError:
        return None


def validar_plano(plano, ultimo):
    """Valida a intenção já estruturada; não recebe filtros ou linguagem SQL."""
    if not isinstance(plano, dict) or set(plano) - {'metrica', 'periodicidade', 'ano'}:
        raise ValueError('Plano de análise inválido.')
    metrica = plano.get('metrica')
    periodicidade = plano.get('periodicidade')
    ano = plano.get('ano', _ultimo_ano(ultimo))
    if metrica not in METRICAS or periodicidade not in PERIODICIDADES:
        raise ValueError('Métrica ou periodicidade inválida.')
    if not isinstance(ano, int) or isinstance(ano, bool) or not 1900 <= ano <= 2199:
        raise ValueError('Ano inválido.')
    return {'metrica': metrica, 'periodicidade': periodicidade, 'ano': ano}


def catalogo():
    """Opções que a camada de conversa pode oferecer sem inventar cálculos."""
    return {'metricas': [{'id': chave, 'titulo': titulo, 'unidade': unidade}
                          for chave, (titulo, unidade) in METRICAS.items()],
            'periodicidades': sorted(PERIODICIDADES)}


def _fim_mes(ano, mes):
    return f'{ano}-{mes:02}-{calendar.monthrange(ano, mes)[1]:02}'


def _meses(ano):
    return [(f'{ano}-{mes:02}', f'{ano}-{mes:02}-01', _fim_mes(ano, mes))
            for mes in range(1, 13)]


def _movimentos_resultado(mov, contas, inicio, fim):
    por_id = {str(c['conta_id']): c for c in contas}
    folhas = {str(conta_id) for conta_id in contas_folha(contas)}
    return [x for x in mov if inicio <= _data(x.get('data')) <= fim
            and por_id.get(str(x.get('conta_id')), {}).get('grupo') == 'resultado'
            and str(x.get('conta_id')) in folhas
            and x.get('tipo') not in {'abertura', 'encerramento'}]


def _periodo_mensal(mov, contas, metrica, periodo, inicio, fim, primeiro, ultimo):
    if fim < primeiro:
        return None, {'motivo': 'período anterior ao primeiro lançamento'}
    if inicio > ultimo:
        return None, {'motivo': 'período posterior ao último lançamento'}
    if metrica == 'liquidez_corrente':
        return _liquidez(mov, contas, periodo, fim, ultimo)
    fatos = _movimentos_resultado(mov, contas, inicio, fim)
    if not fatos:
        return None, {'movimentos_resultado': 0, 'motivo': 'sem movimento de resultado'}
    if metrica == 'faturamento' and not any(
            c.get('grupo') == 'resultado' and c.get('linha_dre') == 'receita_bruta'
            for c in contas):
        return None, {'movimentos_resultado': len(fatos), 'motivo': 'sem conta receita_bruta'}
    # Fatos de abertura e encerramento não podem reaparecer pela chamada ao
    # motor comum; este conjunto já contém somente folhas de resultado válidas.
    linhas = demonstrativo(fatos, contas, periodo, 'mensal')['dre']['linhas_centavos']
    return _valor_linha(linhas, metrica if metrica != 'faturamento' else 'receita_bruta'), {
        'movimentos_resultado': len(fatos), 'linhas_dre': dict(linhas),
    }


def _classe(conta):
    return conta.get('classe_bp') or conta.get('classificacao_balanco')


def _liquidez(mov, contas, periodo, fim, ultimo):
    folhas = contas_folha(contas)
    por_id = {str(c['conta_id']): c for c in contas}
    relevantes = [por_id[str(conta_id)] for conta_id in folhas
                  if por_id[str(conta_id)].get('grupo') in {'ativo', 'passivo'}]
    permitidas = {
        'ativo': {'circulante', 'ativo_circulante', 'nao_circulante', 'ativo_nao_circulante'},
        'passivo': {'circulante', 'passivo_circulante', 'nao_circulante', 'passivo_nao_circulante'},
    }
    sem_classe = [str(c['conta_id']) for c in relevantes if _classe(c) not in permitidas[c['grupo']]]
    if sem_classe:
        return None, {'contas_sem_classificacao_balanco': sem_classe}
    ac = [c for c in relevantes if c.get('grupo') == 'ativo' and
          _classe(c) in {'circulante', 'ativo_circulante'}]
    pc = [c for c in relevantes if c.get('grupo') == 'passivo' and
          _classe(c) in {'circulante', 'passivo_circulante'}]
    if not ac or not pc:
        return None, {'contas_ativo_circulante': [str(c['conta_id']) for c in ac],
                      'contas_passivo_circulante': [str(c['conta_id']) for c in pc]}
    saldos = demonstrativo(mov, contas, periodo, 'mensal')['balanco']['saldos_dc_por_conta']
    ativo = sum(saldos.get(str(c['conta_id']), 0) for c in ac)
    passivo = -sum(saldos.get(str(c['conta_id']), 0) for c in pc)
    return (ativo / passivo if passivo else None), {
        'fim_mes': fim, 'corte_importado': min(fim, ultimo), 'ativo_circulante_centavos': ativo,
        'passivo_circulante_centavos': passivo,
        'contas_ativo_circulante': [str(c['conta_id']) for c in ac],
        'contas_passivo_circulante': [str(c['conta_id']) for c in pc],
    }


def _ponto(periodo, inicio, fim, valor, memoria, parcial=False, metrica=None):
    ano, mes = inicio[:4], inicio[5:7]
    label = f'{mes}/{ano}' if '-T' not in periodo else f'{periodo[-1]}T/{ano}'
    url = (f'/balancete?tipo=mes-a-mes&data_de={inicio}&data_ate={fim}'
           if metrica == 'liquidez_corrente' else f'/razao?data_de={inicio}&data_ate={fim}')
    return {'periodo': periodo, 'label': label, 'inicio': inicio, 'fim': fim,
            'valor': valor, 'anterior': None, 'variacao': None,
            'variacao_percentual': None, 'parcial': parcial, 'memoria': memoria,
            'url': url}


def _variacoes(pontos):
    anterior = None
    for ponto in pontos:
        if anterior is not None and not ponto['parcial'] and not anterior['parcial']:
            atual, base = ponto['valor'], anterior['valor']
            if atual is not None and base is not None:
                ponto['anterior'] = base
                ponto['variacao'] = atual - base
                ponto['variacao_percentual'] = None if base == 0 else 100 * (atual - base) / abs(base)
        anterior = ponto


def _trimestre(mensais, ano, trimestre, metrica, ultimo):
    """Consolida três pontos mensais, preservando a cobertura incompleta."""
    inicio, fim = mensais[0]['inicio'], mensais[-1]['fim']
    presentes = [p for p in mensais if p['valor'] is not None]
    parcial = bool(presentes) and (len(presentes) != 3 or bool(ultimo and ultimo < fim) or any(p['parcial'] for p in mensais))
    valor = (sum(p['valor'] for p in presentes) if presentes and metrica != 'liquidez_corrente'
             else (presentes[-1]['valor'] if presentes and metrica == 'liquidez_corrente' else None))
    memoria = {'meses': [p['periodo'] for p in mensais],
               'pontos_mensais': [p['memoria'] for p in mensais]}
    return _ponto(f'{ano}-T{trimestre}', inicio, fim, valor, memoria, parcial, metrica)


def construir(mov, contas, plano):
    """Monta pontos auditáveis somente a partir dos lançamentos fornecidos."""
    datas = [_data(x.get('data')) for x in mov if _data(x.get('data'))]
    primeiro, ultimo = min(datas, default=None), max(datas, default=None)
    plano = validar_plano(plano, ultimo)
    metrica, periodicidade, ano = plano['metrica'], plano['periodicidade'], plano['ano']
    avisos, mensais = [], []
    if metrica == 'faturamento' and not any(
            c.get('grupo') == 'resultado' and c.get('linha_dre') == 'receita_bruta'
            for c in contas):
        avisos.append('Faturamento ausente: não há conta classificada como receita_bruta.')
    def ponto_mensal(periodo, inicio, fim):
        valor, memoria = _periodo_mensal(mov, contas, metrica, periodo, inicio, fim, primeiro or '', ultimo or '')
        if metrica == 'liquidez_corrente' and valor is None:
            if memoria.get('contas_sem_classificacao_balanco'):
                aviso = 'Liquidez corrente ausente: classificação de balanço insuficiente.'
            elif memoria.get('passivo_circulante_centavos') == 0:
                aviso = 'Liquidez corrente ausente: passivo circulante igual a zero.'
            elif fim <= (ultimo or ''):
                aviso = 'Liquidez corrente ausente: faltam contas classificadas no ativo ou passivo circulante.'
            else:
                aviso = None
            if aviso and aviso not in avisos:
                avisos.append(aviso)
        return _ponto(periodo, inicio, fim, valor, memoria,
                      parcial=bool((ultimo and inicio <= ultimo < fim) or (primeiro and inicio < primeiro <= fim)), metrica=metrica)

    for periodo, inicio, fim in _meses(ano):
        mensais.append(ponto_mensal(periodo, inicio, fim))
    anterior = None
    if ano > 1900:
        if periodicidade == 'mensal':
            periodo, inicio, fim = _meses(ano - 1)[-1]
            anterior = ponto_mensal(periodo, inicio, fim)
        else:
            anterior = _trimestre([ponto_mensal(*mes) for mes in _meses(ano - 1)[-3:]], ano - 1, 4, metrica, ultimo)
    if periodicidade == 'mensal':
        pontos = mensais
    else:
        pontos = []
        for trimestre in range(4):
            bloco = mensais[trimestre * 3:trimestre * 3 + 3]
            ponto = _trimestre(bloco, ano, trimestre + 1, metrica, ultimo)
            pontos.append(ponto)
            if ponto['parcial'] and 'Há trimestre incompleto; a variação não foi calculada.' not in avisos:
                avisos.append('Há trimestre incompleto; a variação não foi calculada.')
    _variacoes(([anterior] if anterior is not None else []) + pontos)
    titulo, unidade = METRICAS[metrica]
    formula = {
        'liquidez_corrente': 'Ativo circulante / passivo circulante no fechamento de cada período',
        'faturamento': 'Créditos − débitos nas contas de Receita bruta; abertura e encerramento excluídos',
        'receita_liquida': 'Receita bruta + deduções (com sinal da DRE de referência)',
        'resultado': 'Soma das receitas, custos e despesas da DRE de referência',
        'ebitda': 'Receita líquida + custos + pessoal + estrutura + outras linhas operacionais da DRE de referência',
    }[metrica] + '. AH = (atual − anterior) / |anterior| × 100; base zero ou período incompleto: sem percentual.'
    return {'titulo': titulo, 'metrica': metrica, 'unidade': unidade,
            'periodicidade': periodicidade, 'ano': ano, 'pontos': pontos,
            'avisos': avisos, 'formula': formula, 'ultimo_importado': ultimo}
