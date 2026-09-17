"""Exportador de EFD ICMS/IPI em RASCUNHO — corte essencial.

Gera o arquivo mensal com o bloco 0 (cadastros), blocos B/D/G/H/K/1 vazios,
bloco C (C100/C170 no leiaute de ICMS com C190 consolidando por CST×CFOP×
alíquota), bloco E (apuração de ICMS e IPI) e bloco 9 com contagens, a partir
dos documentos e itens cadastrados em /nf.

O arquivo é um RASCUNHO: o COD_VER vigente, o perfil (fixo em B) e o
posicionamento completo dos campos precisam ser conferidos pelo contador no
PVA antes de qualquer uso oficial. O app não assina nem transmite.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

COD_VER_PADRAO = '017'
CST_ICMS_VALIDOS = {'00', '10', '20', '30', '40', '41', '50', '51', '60', '70', '90'}
CST_IPI_VALIDOS = {'00', '49', '50', '99', '01', '02', '03', '04', '05', '51', '52', '53', '54', '55'}

CAMPOS_MINIMOS = {'0000': 13, '0001': 1, '0100': 10, '0150': 11, '0190': 2, '0200': 8, '0990': 1,
                  'B001': 1, 'B990': 1,
                  'C001': 1, 'C100': 15, 'C170': 19, 'C190': 11, 'C990': 1,
                  'D001': 1, 'D990': 1,
                  'E001': 1, 'E100': 3, 'E110': 12, 'E200': 3, 'E500': 2, 'E510': 6, 'E520': 1, 'E990': 1,
                  'G001': 1, 'G990': 1, 'H001': 1, 'H990': 1, 'K001': 1, 'K990': 1,
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
    """Consolida ICMS e IPI por CST/CFOP/alíquota e confere bc×aliq ≈ imposto."""
    avisos = []
    icms = defaultdict(lambda: {'vl_opr': 0, 'bc': 0, 'vl': 0})
    ipi = defaultdict(lambda: {'vl_cont': 0, 'bc': 0, 'vl': 0})
    divergencia = 0
    for it in itens:
        cst_icms = (it.get('cst_icms') or '').strip()
        if not cst_icms:
            avisos.append(f'Item {it["id"]} sem CST-ICMS: não entra na apuração.')
        bc_icms = int(it.get('vl_bc_icms_centavos') or 0)
        aliq_icms = float(it.get('aliq_icms') or 0)
        vl_icms = int(it.get('vl_icms_centavos') or 0)
        if bc_icms or aliq_icms or vl_icms:
            esperado = round(bc_icms * aliq_icms / 100)
            if esperado != vl_icms and divergencia < 3:
                avisos.append(f'Item {it["id"]}: ICMS declarado ({vl_icms}) difere de bc×aliq ({esperado}).')
                divergencia += 1
            linha = icms[(cst_icms, it.get('cfop') or '', f'{aliq_icms:.2f}')]
            linha['vl_opr'] += int(it.get('vl_item_centavos') or 0)
            linha['bc'] += bc_icms
            linha['vl'] += vl_icms
        bc_ipi = int(it.get('vl_bc_ipi_centavos') or 0)
        vl_ipi = int(it.get('vl_ipi_centavos') or 0)
        if bc_ipi or vl_ipi:
            linha = ipi[(it.get('cst_ipi') or '99', it.get('cfop') or '')]
            linha['vl_cont'] += bc_ipi
            linha['bc'] += bc_ipi
            linha['vl'] += vl_ipi
    debitos = 0
    creditos = 0
    for it in itens:
        tipo = None
        for d in documentos:
            if d['id'] == it['documento_id']:
                tipo = d['tipo']
                break
        if tipo == 'saida':
            debitos += int(it.get('vl_icms_centavos') or 0)
        elif tipo == 'entrada':
            creditos += int(it.get('vl_icms_centavos') or 0)
    ipi_debitos = sum(v['vl'] for v in ipi.values())
    if debitos == 0 and creditos == 0:
        avisos.append('Nenhum valor de ICMS nos itens: a apuração sai zerada.')
    return dict(icms=icms, ipi=ipi, avisos=avisos, icms_debitos=debitos, icms_creditos=creditos,
                saldo_icms=debitos - creditos,
                icms_recolher=max(0, debitos - creditos), icms_credor=max(0, creditos - debitos),
                ipi_total=ipi_debitos, n_docs=len(documentos), n_itens=len(itens))


def gerar(empresa, participantes, documentos, itens, periodo):
    """Monta a EFD ICMS/IPI rascunho do mês e devolve (texto, avisos)."""
    avisos = []
    if not empresa or len(''.join(ch for ch in (empresa.get('cnpj') or '') if ch.isdigit())) != 14:
        raise ValueError('Cadastre o CNPJ da empresa antes de gerar a EFD ICMS/IPI.')
    if not (empresa.get('uf') or '').strip():
        raise ValueError('Cadastre a UF da empresa antes de gerar a EFD ICMS/IPI.')
    if not (empresa.get('ie') or '').strip():
        avisos.append('Inscrição estadual da empresa ausente (registro 0000 incompleto).')
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
        _linha('0000', [COD_VER_PADRAO, '0', _dma(ini), _dma(fim), (empresa.get('razao_social') or '')[:100], cnpj,
                        (empresa.get('uf') or '')[:2], (empresa.get('ie') or '')[:20], (empresa.get('cod_mun') or '')[:7],
                        '', '', 'B', '0']),
        _linha('0001', ['0']),
        _linha('0100', ['R', (empresa.get('logradouro') or '')[:200], (empresa.get('numero') or '')[:20],
                        (empresa.get('complemento') or '')[:100], (empresa.get('bairro') or '')[:100],
                        (empresa.get('uf') or '')[:2], (empresa.get('cod_mun') or '')[:7],
                        (empresa.get('cep') or '')[:8], '', '']),
        _linha('0190', ['UN', 'Unidade']),
    ]
    for chave, p in participe.items():
        doc = ''.join(ch for ch in (p.get('documento') or '') if ch.isdigit())
        linhas.append(_linha('0150', [(p.get('nome') or '')[:100], '1058', doc if len(doc) == 14 else '',
                                      doc if len(doc) == 11 else '', (p.get('ie') or '')[:20],
                                      (p.get('cod_mun') or '')[:7], '', '', '', '', '']))
    for descricao in descricoes:
        chave = descricao.casefold().strip()
        linhas.append(_linha('0200', [cod_item[chave], descricao[:200], '', '', 'UN', '00', '', '']))
    linhas.append(_linha('0990', [len(linhas) + 1]))

    linhas.append(_linha('B001', ['1']))
    linhas.append(_linha('B990', ['2']))

    c_qtd = 0
    linhas.append(_linha('C001', ['0']))
    for d in [x for x in documentos if x['tipo'] in ('saida', 'entrada')]:
        c_qtd += 1
        doc_itens = itens_por_doc.get(d['id'], [])
        vl_icms_doc = sum(int(x.get('vl_icms_centavos') or 0) for x in doc_itens)
        vl_ipi_doc = sum(int(x.get('vl_ipi_centavos') or 0) for x in doc_itens)
        linhas.append(_linha('C100', ['0' if d['tipo'] == 'saida' else '1', '0', d['participante'][:60], '55',
                                      '0', d['serie'][:3], d['numero'][:20], '', _dma(_data_iso(d['data_emissao'])),
                                      _dma(_data_iso(d['data_emissao'])), int(d['valor_total_centavos']) + vl_ipi_doc, '0',
                                      0, 0, int(d['valor_total_centavos'])]))
        for i, it in enumerate(doc_itens, 1):
            c_qtd += 1
            linhas.append(_linha('C170', [i, item_cod.get(it['id'], ''), (it['descricao'] or '')[:200],
                                          '', 'UN', int(it['vl_item_centavos']), 0, '0',
                                          it.get('cst_icms') or '90', it['cfop'][:4] or '', '',
                                          int(it.get('vl_bc_icms_centavos') or 0), str(it.get('aliq_icms') or 0),
                                          int(it.get('vl_icms_centavos') or 0), 0, 0,
                                          int(it.get('vl_bc_ipi_centavos') or 0), str(it.get('aliq_ipi') or 0),
                                          int(it.get('vl_ipi_centavos') or 0)]))
        consolidado = defaultdict(lambda: {'vl_opr': 0, 'bc': 0, 'vl': 0, 'bc_st': 0, 'vl_st': 0, 'ipi': 0})
        for it in doc_itens:
            chave = (it.get('cst_icms') or '90', it['cfop'][:4] or '', f'{float(it.get("aliq_icms") or 0):.2f}')
            linha = consolidado[chave]
            linha['vl_opr'] += int(it.get('vl_item_centavos') or 0)
            linha['bc'] += int(it.get('vl_bc_icms_centavos') or 0)
            linha['vl'] += int(it.get('vl_icms_centavos') or 0)
            linha['ipi'] += int(it.get('vl_ipi_centavos') or 0)
        for (cst_icms, cfop, aliq), v in sorted(consolidado.items()):
            c_qtd += 1
            linhas.append(_linha('C190', [cst_icms, cfop, aliq, v['vl_opr'], v['bc'], v['vl'],
                                          v['bc_st'], v['vl_st'], 0, v['ipi'], '']))
    linhas.append(_linha('C990', [c_qtd + 2]))

    linhas.append(_linha('D001', ['1']))
    linhas.append(_linha('D990', ['2']))

    e_qtd = 0
    linhas.append(_linha('E001', ['0']))
    linhas.append(_linha('E100', [(empresa.get('uf') or '')[:2], _dma(ini), _dma(fim)]))
    linhas.append(_linha('E110', [numeros['icms_debitos'], 0, 0, numeros['icms_creditos'], 0, 0, 0,
                                  numeros['saldo_icms'], 0, numeros['icms_recolher'], numeros['icms_credor'], '']))
    e_qtd += 2
    linhas.append(_linha('E200', [(empresa.get('uf') or '')[:2], _dma(ini), _dma(fim)]))
    e_qtd += 1
    linhas.append(_linha('E500', [_dma(ini), _dma(fim)]))
    e_qtd += 1
    for (cst_ipi, cfop), v in sorted(numeros['ipi'].items()):
        e_qtd += 1
        linhas.append(_linha('E510', [cst_ipi[:2], cfop[:4], v['vl_cont'], v['bc'], v['vl'], 0]))
    linhas.append(_linha('E520', [numeros['ipi_total']]))
    e_qtd += 1
    linhas.append(_linha('E990', [e_qtd + 2]))

    linhas.append(_linha('G001', ['1']))
    linhas.append(_linha('G990', ['2']))
    linhas.append(_linha('H001', ['1']))
    linhas.append(_linha('H990', ['2']))
    linhas.append(_linha('K001', ['1']))
    linhas.append(_linha('K990', ['2']))
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
