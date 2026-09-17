"""Exportador de ECF (Escrituração Contábil Fiscal) em RASCUNHO — Lucro Presumido.

Gera o arquivo anual (blocos 0, J, M, N e Y essenciais) calculando IRPJ/CSLL
presumidos a partir dos lançamentos importados e das informações cadastradas
em /ecf. Blocos de Lucro Real (L, K, livro AP), eventos (X, U, Q) e regimes
Simples/Real não são emitidos.

O arquivo é um RASCUNHO: o leiaute e a versão (COD_VER) vigentes de cada
ano-calendário precisam ser conferidos pelo contador no PVA da Receita antes
de qualquer uso oficial. O app não assina nem transmite.
"""
from datetime import date

COD_VER_PADRAO = '0011'
TRIMESTRES = (('01-01', '03-31'), ('04-01', '06-30'), ('07-01', '09-30'), ('10-01', '12-31'))
LIMITE_ADICIONAL_TRI = 60000 * 100

CAMPOS_MINIMOS = {'0000': 14, '0001': 1, '0010': 1, '0020': 2, '0030': 11, '0035': 5, '0450': 4,
                  'J005': 3, 'J030': 11, 'M300': 2, 'M310': 6, 'M410': 3, 'M415': 3, 'M500': 3,
                  'N600': 6, 'N650': 4, 'N630': 2, 'N660': 2, 'N670': 4,
                  'Y180': 2, 'Y520': 4, 'Y540': 2, 'Y550': 2, 'Y680': 4, 'Y690': 3,
                  'Y980': 3, 'Y990': 2, '9999': 2}


def _linha(tipo, campos):
    return '|' + '|'.join([tipo] + ['' if c is None else str(c) for c in campos]) + '|'


def _dma(iso):
    return iso[8:10] + iso[5:7] + iso[:4]


def _data_iso(valor):
    return valor.isoformat() if hasattr(valor, 'isoformat') else str(valor)[:10]


def _por_centavos(pct):
    return float(pct) / 100.0


def _limites_trimestre(ano, indice):
    inicio, fim = TRIMESTRES[indice]
    return f'{ano}-{inicio}', f'{ano}-{fim}'


def calcular(empresa, contas, mov, parametros, contas_pb, lancamentos_pb, conciliacao, ano):
    """Números da apuração presumida do ano. Usado pelo gerador e pela tela /ecf."""
    avisos = []
    if not empresa or len(''.join(ch for ch in (empresa.get('cnpj') or '') if ch.isdigit())) != 14:
        raise ValueError('Cadastre o CNPJ da empresa antes de gerar a ECF.')
    regime = (empresa.get('regime') or '').casefold()
    if regime == 'simples':
        raise ValueError('Empresa do Simples Nacional não entrega ECF.')
    if regime not in ('presumido', 'arbitrado'):
        raise ValueError(f'Regime "{empresa.get("regime")}" sem blocos suportados nesta fase (apenas Presumido/Arbitrado).')
    if not parametros:
        raise ValueError(f'Parametrize o ano-calendário {ano} em Fiscal → ECF antes de gerar o arquivo.')
    if not (empresa.get('ie') and empresa.get('cod_mun')):
        avisos.append('IE e/ou código IBGE do município ausentes na empresa (registro 0030 incompleto).')
    sem_ref = [c['conta_id'] for c in contas if c.get('analitica') and not c.get('cod_referencial')]
    if sem_ref:
        avisos.append(f'{len(sem_ref)} conta(s) analítica(s) sem código referencial (registro 0450 em branco).')

    receita_ids = {c['conta_id'] for c in contas if c.get('grupo') == 'resultado' and c.get('analitica') and c.get('linha_dre') == 'receita_bruta'}
    deducao_ids = {c['conta_id'] for c in contas if c.get('grupo') == 'resultado' and c.get('analitica') and c.get('linha_dre') == 'deducoes'}
    resultado_ids = {c['conta_id'] for c in contas if c.get('grupo') == 'resultado' and c.get('analitica')}

    def liquido(ids, ini, fim):
        total = 0
        for m in mov:
            data = _data_iso(m['data'])
            if ini <= data <= fim and m['conta_id'] in ids and m.get('tipo') != 'encerramento':
                total += m['credito_centavos'] - m['debito_centavos']
        return total

    trimestres = []
    pct_irpj = _por_centavos(parametros['pct_presuncao_irpj'])
    pct_csll = _por_centavos(parametros['pct_presuncao_csll'])
    for indice in range(4):
        ini, fim = _limites_trimestre(ano, indice)
        receita = liquido(receita_ids, ini, fim) + liquido(deducao_ids, ini, fim)
        base_irpj = round(receita * pct_irpj)
        irpj = round(base_irpj * 0.15)
        adicional = round(max(0, base_irpj - LIMITE_ADICIONAL_TRI) * 0.10) if parametros.get('adicional') else 0
        base_csll = round(receita * pct_csll)
        csll = round(base_csll * 0.09)
        trimestres.append(dict(per=f'{ano}T{indice + 1}', inicio=ini, fim=fim, receita=receita,
                               base_irpj=base_irpj, irpj=irpj, adicional=adicional,
                               base_csll=base_csll, csll=csll))
    receita_bruta = sum(t['receita'] for t in trimestres)
    lucro_contabil = liquido(resultado_ids, f'{ano}-01-01', f'{ano}-12-31')
    conciliacao_total = sum(int(c['valor_centavos']) for c in conciliacao)
    lucro_fiscal = lucro_contabil + conciliacao_total
    parte_b_total = sum((int(l['valor_centavos']) if l['tipo'] == 'A' else -int(l['valor_centavos']))
                        for l in lancamentos_pb if l['tipo'] in ('A', 'B'))
    if receita_bruta == 0:
        avisos.append('Receita bruta do ano zerada: a ECF sai sem base de cálculo.')
    if not lancamentos_pb:
        avisos.append('Nenhum lançamento na Parte B: os blocos M sairão vazios.')
    if not conciliacao and parte_b_total != lucro_fiscal:
        avisos.append('Sem conciliação cadastrada e Parte B difere do lucro fiscal: confira antes de transmitir.')
    if conciliacao and parte_b_total and parte_b_total != lucro_fiscal:
        avisos.append(f'Conciliação + lucro contábil ({lucro_fiscal}) difere da Parte B ({parte_b_total}).')
    if parametros.get('forma_tributacao') == 'mensal_estimativa':
        avisos.append('Estimativa mensal emitida em trimestres agregados: confira as datas no PVA.')
    return dict(avisos=avisos, receita_bruta=receita_bruta, lucro_contabil=lucro_contabil,
                conciliacao_total=conciliacao_total, lucro_fiscal=lucro_fiscal,
                parte_b_total=parte_b_total, trimestres=trimestres,
                total_irpj=sum(t['irpj'] + t['adicional'] for t in trimestres),
                total_csll=sum(t['csll'] for t in trimestres))


def gerar_ecf(empresa, contas, mov, participantes, parametros, contas_pb, lancamentos_pb, conciliacao, ano):
    """Monta o arquivo ECF rascunho do ano e devolve (texto, avisos)."""
    numeros = calcular(empresa, contas, mov, parametros, contas_pb, lancamentos_pb, conciliacao, ano)
    avisos = list(numeros['avisos'])
    cnpj = ''.join(ch for ch in (empresa.get('cnpj') or '') if ch.isdigit())
    ini, fim = f'{ano}-01-01', f'{ano}-12-31'
    linhas = [
        _linha('0000', [COD_VER_PADRAO, '0', _dma(ini), _dma(fim), (empresa.get('razao_social') or '')[:80], cnpj,
                        (empresa.get('uf') or '')[:2], (empresa.get('ie') or '')[:20], (empresa.get('cod_mun') or '')[:7],
                        '0', '0', '0', '1', '']),
        _linha('0001', ['0']),
        _linha('0010', ['3' if (empresa.get('regime') or '').casefold() == 'arbitrado' else '2']),
        _linha('0020', ['1', '1'] if parametros['forma_tributacao'] == 'mensal_estimativa' else ['3', '3']),
        _linha('0030', ['1', 'R', (empresa.get('logradouro') or '')[:200], (empresa.get('numero') or '')[:20],
                        (empresa.get('complemento') or '')[:100], (empresa.get('bairro') or '')[:100],
                        (empresa.get('uf') or '')[:2], (empresa.get('cod_mun') or '')[:7],
                        (empresa.get('cep') or '')[:8], '', '']),
    ]
    for p in participantes:
        doc = ''.join(ch for ch in (p.get('documento') or '') if ch.isdigit())
        linhas.append(_linha('0035', [(p.get('nome') or '')[:100], '', doc if len(doc) == 14 else '',
                                      doc if len(doc) == 11 else '', '']))
    for c in sorted(contas, key=lambda x: (x.get('nivel', 1), x['conta_id'])):
        linhas.append(_linha('0450', [c['conta_id'][:60], (c.get('cod_referencial') or '')[:60],
                                      c.get('nivel', 1), 'A' if c.get('analitica') else 'S']))
    linhas.append(_linha('J005', [_dma(ini), _dma(fim), 'BAL']))
    total_mov_d = total_mov_c = 0
    for c in sorted(contas, key=lambda x: (x.get('nivel', 1), x['conta_id'])):
        if not c.get('analitica'):
            continue
        saldo_ini = 0
        for m in mov:
            if m['conta_id'] == c['conta_id'] and _data_iso(m['data']) <= f'{ano - 1}-12-31':
                saldo_ini += m['debito_centavos'] - m['credito_centavos']
        mov_d = sum(m['debito_centavos'] for m in mov if m['conta_id'] == c['conta_id'] and ini <= _data_iso(m['data']) <= fim)
        mov_c = sum(m['credito_centavos'] for m in mov if m['conta_id'] == c['conta_id'] and ini <= _data_iso(m['data']) <= fim)
        saldo_fin = saldo_ini + mov_d - mov_c
        id_d, id_c = (saldo_ini, 0) if saldo_ini >= 0 else (0, -saldo_ini)
        fd, fc = (saldo_fin, 0) if saldo_fin >= 0 else (0, -saldo_fin)
        total_mov_d += mov_d; total_mov_c += mov_c
        linhas.append(_linha('J030', [_dma(ini), _dma(fim), 'BAL', c['conta_id'][:60], (c.get('cod_referencial') or '')[:60],
                                      id_d, id_c, mov_d, mov_c, fd, fc]))
    if total_mov_d != total_mov_c:
        avisos.append(f'Balancete não fecha no ano: débitos {total_mov_d} ≠ créditos {total_mov_c}.')

    for conta_pb in sorted(contas_pb, key=lambda x: x['codigo']):
        linhas.append(_linha('M410', [conta_pb['codigo'], (conta_pb['descricao'] or '')[:200], '1']))
    por_periodo = {}
    for l in sorted(lancamentos_pb, key=lambda x: (x['periodo'], _data_iso(x['data']), x['id'])):
        por_periodo.setdefault(l['periodo'], []).append(l)
    for periodo in sorted(por_periodo):
        grupo = por_periodo[periodo]
        linhas.append(_linha('M300', [periodo, len(grupo)]))
        total = 0
        for numero, l in enumerate(grupo, 1):
            valor = int(l['valor_centavos'])
            total += valor if l['tipo'] == 'A' else -valor
            linhas.append(_linha('M310', [numero, _dma(_data_iso(l['data'])), l['conta_pb'], l['tipo'], valor, (l['historico'] or '')[:200]]))
            linhas.append(_linha('M415', [numero, l['conta_pb'], valor]))
        linhas.append(_linha('M500', [periodo, 'A', total]))

    for t in numeros['trimestres']:
        linhas.append(_linha('N600', [t['per'], t['receita'], t['base_irpj'], t['irpj'], t['adicional'], t['irpj'] + t['adicional']]))
        linhas.append(_linha('N650', [t['per'], t['receita'], t['base_csll'], t['csll']]))
    linhas.append(_linha('N630', [numeros['total_irpj']]))
    linhas.append(_linha('N660', [numeros['total_csll']]))
    linhas.append(_linha('N670', [str(ano), numeros['total_irpj'], numeros['total_csll'], numeros['total_irpj'] + numeros['total_csll']]))

    linhas.append(_linha('Y180', ['', numeros['lucro_contabil']]))
    linhas.append(_linha('Y520', [numeros['receita_bruta'], 0, 0, numeros['lucro_contabil']]))
    linhas.append(_linha('Y540', [numeros['lucro_contabil'], numeros['lucro_contabil']]))
    linhas.append(_linha('Y550', [numeros['lucro_contabil'], numeros['lucro_fiscal']]))
    for c in sorted(conciliacao, key=lambda x: (x['ordem'], x['id'])):
        linhas.append(_linha('Y680', [(c.get('conta_id') or '')[:60], int(c['valor_centavos']), '', (c['historico'] or '')[:200]]))
    linhas.append(_linha('Y690', [numeros['lucro_contabil'], numeros['conciliacao_total'], numeros['lucro_fiscal']]))
    linhas.append(_linha('Y980', ['0', COD_VER_PADRAO, (empresa.get('razao_social') or '')[:80]]))
    linhas.append(_linha('Y990', [cnpj, (empresa.get('razao_social') or '')[:80]]))
    linhas.append(_linha('9999', ['0', len(linhas) + 1]))
    return '\r\n'.join(linhas) + '\r\n', avisos
