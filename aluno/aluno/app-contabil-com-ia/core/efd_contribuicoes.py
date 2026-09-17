"""Exportador de EFD-Contribuições (PIS/COFINS) em RASCUNHO — corte essencial.

Gera o arquivo mensal com os blocos 0 (cadastros), A (serviços), C (NF
mercantis), F vazio, M (consolidações PIS/COFINS por CST) e 9 (contagens),
a partir dos documentos e itens cadastrados em /nf. Blocos D, I, J, P, R, T
e retificações não são emitidos.

O arquivo é um RASCUNHO: o COD_VER vigente do período e o posicionamento
completo dos campos (especialmente C170/A170) precisam ser conferidos pelo
contador no PVA antes de qualquer uso oficial. O app não assina nem transmite.
"""
from collections import Counter
from datetime import date, timedelta

COD_VER_PADRAO = '0030'
CSTS_VALIDOS = {'01', '02', '04', '05', '06', '07', '08', '09', '49', '50', '51', '52', '53',
                '54', '55', '56', '60', '61', '62', '63', '64', '65', '66', '70', '71', '72',
                '73', '74', '75', '98', '99'}

CAMPOS_MINIMOS = {'0000': 11, '0001': 1, '0100': 10, '0110': 1, '0150': 11, '0190': 2, '0200': 8, '0990': 1,
                  'A001': 1, 'A100': 12, 'A170': 12, 'A990': 1,
                  'C001': 1, 'C100': 15, 'C170': 12, 'C990': 1,
                  'F001': 1, 'F990': 1,
                  'M001': 1, 'M100': 5, 'M200': 9, 'M500': 5, 'M600': 9, 'M990': 1,
                  '1001': 1, '1990': 1,
                  '9001': 1, '9900': 3, '9990': 1, '9999': 1}


def _linha(tipo, campos):
    return '|' + '|'.join([tipo] + ['' if c is None else str(c) for c in campos]) + '|'


def _dma(iso):
    return iso[8:10] + iso[5:7] + iso[:4]


def _data_iso(valor):
    return valor.isoformat() if hasattr(valor, 'isoformat') else str(valor)[:10]


def _fim_mes(periodo):
    ano, mes = int(periodo[:4]), int(periodo[5:7])
    return ((date(ano + (mes == 12), mes % 12 + 1, 1)) - timedelta(days=1)).isoformat()


def calcular(documentos, itens):
    """Consolida PIS/COFINS por CST e confere bc×aliq ≈ contribuição."""
    avisos = []
    pis, cofins = {}, {}
    divergencia = 0
    for it in itens:
        for trib, cst_chave, bc_chave, aliq_chave, vl_chave in (
                ('pis', 'cst_pis', 'vl_bc_pis_centavos', 'aliq_pis', 'vl_pis_centavos'),
                ('cofins', 'cst_cofins', 'vl_bc_cofins_centavos', 'aliq_cofins', 'vl_cofins_centavos')):
            cst = (it.get(cst_chave) or '').strip()
            if not cst:
                avisos.append(f'Item {it["id"]} sem CST-{trib.upper()}: não entra nas consolidações.')
                continue
            bc = int(it.get(bc_chave) or 0)
            aliq = float(it.get(aliq_chave) or 0)
            vl = int(it.get(vl_chave) or 0)
            esperado = round(bc * aliq / 100)
            if esperado != vl and divergencia < 3:
                avisos.append(f'Item {it["id"]}: {trib.upper()} declarado ({vl}) difere de bc×aliq ({esperado}).')
                divergencia += 1
            destino = pis if trib == 'pis' else cofins
            linha = destino.setdefault(cst, {'bc': 0, 'vl': 0, 'contab': 0})
            linha['bc'] += bc
            linha['vl'] += vl
            linha['contab'] += int(it.get('vl_item_centavos') or 0)
    if not documentos:
        avisos.append('Nenhum documento no período: a EFD sai sem operações.')
    return dict(pis=pis, cofins=cofins, avisos=avisos,
                total_pis=sum(v['vl'] for v in pis.values()),
                total_cofins=sum(v['vl'] for v in cofins.values()),
                n_docs=len(documentos), n_itens=len(itens))


def gerar(empresa, participantes, documentos, itens, periodo):
    """Monta a EFD-Contribuições rascunho do mês e devolve (texto, avisos)."""
    avisos = []
    if not empresa or len(''.join(ch for ch in (empresa.get('cnpj') or '') if ch.isdigit())) != 14:
        raise ValueError('Cadastre o CNPJ da empresa antes de gerar a EFD-Contribuições.')
    regime = (empresa.get('regime') or '').casefold()
    if regime == 'simples':
        raise ValueError('Empresa do Simples Nacional não entrega EFD-Contribuições.')
    ini = periodo + '-01'
    fim = _fim_mes(periodo)
    itens_por_doc = {}
    for it in itens:
        itens_por_doc.setdefault(it['documento_id'], []).append(it)
    numeros = calcular([d for d in documentos if ini <= _data_iso(d['data_emissao']) <= fim], itens)
    avisos.extend(numeros['avisos'])
    cnpj = ''.join(ch for ch in (empresa.get('cnpj') or '') if ch.isdigit())

    usados = {d['participante'] for d in documentos if d.get('participante')}
    participe = {p['chave']: p for p in participantes if p['chave'] in usados}
    descricoes = []
    vistos = set()
    for it in itens:
        chave = (it['descricao'] or '').casefold().strip()
        if chave and chave not in vistos:
            vistos.add(chave)
            descricoes.append(it['descricao'])
    cod_item = {d.casefold().strip(): f'IT{i:04d}' for i, d in enumerate(descricoes, 1)}
    item_cod = {}
    for it in itens:
        item_cod[it['id']] = cod_item[(it['descricao'] or '').casefold().strip()]

    linhas = [
        _linha('0000', [COD_VER_PADRAO, _dma(ini), _dma(fim), (empresa.get('razao_social') or '')[:100], cnpj,
                        (empresa.get('uf') or '')[:2], (empresa.get('ie') or '')[:20], (empresa.get('cod_mun') or '')[:7],
                        '', '0', '0']),
        _linha('0001', ['0']),
        _linha('0100', ['R', (empresa.get('logradouro') or '')[:200], (empresa.get('numero') or '')[:20],
                        (empresa.get('complemento') or '')[:100], (empresa.get('bairro') or '')[:100],
                        (empresa.get('uf') or '')[:2], (empresa.get('cod_mun') or '')[:7],
                        (empresa.get('cep') or '')[:8], '', '']),
        _linha('0110', ['1' if regime == 'real' else '3']),
        _linha('0190', ['UN', 'Unidade']),
    ]
    for chave, p in participe.items():
        doc = ''.join(ch for ch in (p.get('documento') or '') if ch.isdigit())
        linhas.append(_linha('0150', [(p.get('nome') or '')[:100], '1058', doc if len(doc) == 14 else '',
                                      doc if len(doc) == 11 else '', (p.get('ie') or '')[:20],
                                      (p.get('cod_mun') or '')[:7], '', '', '', '', '']))
        if not (p.get('ie') or '').strip():
            avisos.append(f'Participante "{p.get("nome")}" sem inscrição estadual (registro 0150 incompleto).')
    for descricao in descricoes:
        chave = descricao.casefold().strip()
        linhas.append(_linha('0200', [cod_item[chave], descricao[:200], '', '', 'UN', '00', '', '']))
    linhas.append(_linha('0990', [len(linhas) + 1]))

    a_qtd = 0
    linhas.append(_linha('A001', ['0']))
    for d in [x for x in documentos if x['tipo'] == 'servico']:
        a_qtd += 1
        linhas.append(_linha('A100', ['0' if d['tipo'] == 'saida' else '1', '0', d['participante'][:60], 'NA',
                                      '0', d['serie'][:5], d['numero'][:20], '', _dma(_data_iso(d['data_emissao'])),
                                      _dma(_data_iso(d['data_emissao'])), int(d['valor_total_centavos']), '0']))
        for i, it in enumerate(itens_por_doc.get(d['id'], []), 1):
            a_qtd += 1
            linhas.append(_linha('A170', [i, item_cod.get(it['id'], ''), (it['descricao'] or '')[:200],
                                          int(it['vl_item_centavos']), 0, '1', '0', it['cst_pis'][:2],
                                          int(it['vl_bc_pis_centavos']), str(it['aliq_pis']), int(it['vl_pis_centavos']),
                                          it['cst_cofins'][:2], int(it['vl_bc_cofins_centavos']), str(it['aliq_cofins']),
                                          int(it['vl_cofins_centavos'])]))
    linhas.append(_linha('A990', [a_qtd + 2]))

    c_qtd = 0
    linhas.append(_linha('C001', ['0']))
    for d in [x for x in documentos if x['tipo'] in ('saida', 'entrada')]:
        c_qtd += 1
        linhas.append(_linha('C100', ['0' if d['tipo'] == 'saida' else '1', '0', d['participante'][:60], '55',
                                      '0', d['serie'][:3], d['numero'][:20], '', _dma(_data_iso(d['data_emissao'])),
                                      _dma(_data_iso(d['data_emissao'])), int(d['valor_total_centavos']), '0',
                                      0, 0, int(d['valor_total_centavos'])]))
        for i, it in enumerate(itens_por_doc.get(d['id'], []), 1):
            c_qtd += 1
            linhas.append(_linha('C170', [i, item_cod.get(it['id'], ''), (it['descricao'] or '')[:200],
                                          '', 'UN', int(it['vl_item_centavos']), 0, '0', '', it['cfop'][:4] or '', '', 0,
                                          it['cst_pis'][:2], int(it['vl_bc_pis_centavos']), str(it['aliq_pis']), int(it['vl_pis_centavos']),
                                          it['cst_cofins'][:2], int(it['vl_bc_cofins_centavos']), str(it['aliq_cofins']), int(it['vl_cofins_centavos'])]))
    linhas.append(_linha('C990', [c_qtd + 2]))

    linhas.append(_linha('F001', ['1']))
    linhas.append(_linha('F990', ['2']))

    m_qtd = 0
    linhas.append(_linha('M001', ['0']))
    for cst in sorted(numeros['pis']):
        v = numeros['pis'][cst]
        m_qtd += 1
        linhas.append(_linha('M100', [cst, 0, v['vl'], 0, 0]))
    m_qtd += 1
    linhas.append(_linha('M200', [numeros['total_pis'], numeros['total_pis'], 0, 0, 0, 0, 0, 0, 0]))
    for cst in sorted(numeros['cofins']):
        v = numeros['cofins'][cst]
        m_qtd += 1
        linhas.append(_linha('M500', [cst, 0, v['vl'], 0, 0]))
    m_qtd += 1
    linhas.append(_linha('M600', [numeros['total_cofins'], numeros['total_cofins'], 0, 0, 0, 0, 0, 0, 0]))
    linhas.append(_linha('M990', [m_qtd + 2]))

    linhas.append(_linha('1001', ['1']))
    linhas.append(_linha('1990', ['2']))

    antes_do_9 = len(linhas)
    linhas.append(_linha('9001', ['0']))
    contagem = Counter(l[1:].split('|')[0] for l in linhas)
    k = len(contagem) + 3
    for registro in sorted(contagem):
        linhas.append(_linha('9900', [registro, contagem[registro], '']))
    linhas.append(_linha('9900', ['9900', k, '']))
    linhas.append(_linha('9900', ['9990', '1', '']))
    linhas.append(_linha('9900', ['9999', '1', '']))
    linhas.append(_linha('9990', [k + 2]))
    linhas.append(_linha('9999', [antes_do_9 + k + 3]))
    return '\r\n'.join(linhas) + '\r\n', avisos
