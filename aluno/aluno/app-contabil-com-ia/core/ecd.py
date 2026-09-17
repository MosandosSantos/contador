"""Exportador de ECD (SPED Contábil) em modo RASCUNHO — Release 2.

Gera um arquivo texto no estilo SPED (registros delimitados por barra vertical)
com os blocos essenciais do ECD: abertura, plano de contas (local + referencial),
balancete centralizado (J100) e partidas do diário (J930), com encerramento.

O arquivo é um RASCUNHO para conferência pelo contador no PVA da Receita antes de
qualquer uso oficial: versões, campos e regras mudam a cada ano e podem exigir
ajustes para a norma vigente. O app não assina digitalmente nem envia nada.
"""
from datetime import date

ROTULO_GRUPO = {'ativo': 'A', 'passivo': 'P', 'pl': 'P', 'resultado': 'R', 'pendente': 'X'}


def _linha(tipo, campos):
    corpo = '|'.join([tipo] + [str(c) if c is not None else '' for c in campos])
    return '|' + corpo + '|'


def _contas_ordenadas(contas):
    return sorted(contas, key=lambda c: (c['nivel'], c['conta_id']))


def _saldo_conta(mov, conta_id, ate=None):
    """Saldo devedor(+) / credor(−) em centavos até a data indicada."""
    deb = cred = 0
    for m in mov:
        if m['conta_id'] != conta_id:
            continue
        if ate and str(m['data']) > ate:
            continue
        deb += m['debito_centavos']
        cred += m['credito_centavos']
    return deb - cred


def gerar_ecd(empresa, contas, mov, dt_ini, dt_fim):
    """Monta o arquivo ECD rascunho e devolve (texto, avisos)."""
    avisos = []
    cnpj = ''.join(ch for ch in (empresa.get('cnpj') or '') if ch.isdigit())
    if len(cnpj) != 14:
        raise ValueError('Cadastre o CNPJ da empresa antes de exportar o ECD.')
    sem_ref = [c['conta_id'] for c in contas if c['analitica'] and not c.get('cod_referencial')]
    if sem_ref:
        avisos.append(f'{len(sem_ref)} conta(s) analítica(s) sem código referencial (campo 0500 ficará em branco).')

    linhas = []
    # Layout do 0000 do ECD: LECD (COD_VER) | COD_FIN | DT_INI | DT_FIN | NOME |
    # CNPJ | UF | IE | COD_MUN | IND_SIT_ESP | IND_SIT_INIC
    linhas.append(_linha('0000', ['LECD', '0', dt_ini[8:10] + dt_ini[5:7] + dt_ini[:4], dt_fim[8:10] + dt_fim[5:7] + dt_fim[:4],
                                  (empresa.get('razao_social') or '')[:80], cnpj,
                                  (empresa.get('uf') or '')[:2], '', '', '0', '0']))
    linhas.append(_linha('0001', ['0']))

    # Plano de contas: todas as contas (sintéticas e analíticas) com referencial.
    for c in _contas_ordenadas(contas):
        contas_sped = ['I', 'S'] if c['analitica'] else ['S', 'S']
        linhas.append(_linha('0500', [
            '', c['conta_id'][:60], (c['descricao'] or '')[:60], contas_sped[0], contas_sped[1],
            '1', ROTULO_GRUPO.get(c['grupo'], 'X'), '', '', '', '1', '',
            (c.get('cod_referencial') or '')[:60],
            c.get('natureza') or '', '', '', '', '', '', '', '', '', '', '', '', '',
        ]))

    # Balancete centralizado (J100) por conta analítica.
    contas_por_id = {c['conta_id']: c for c in contas}
    total_dt = total_ct = 0
    for c in _contas_ordenadas(contas):
        if not c['analitica']:
            continue
        saldo = _saldo_conta(mov, c['conta_id'], dt_fim)
        if saldo >= 0:
            vd, vc = saldo, 0
        else:
            vd, vc = 0, -saldo
        cod_ref = (c.get('cod_referencial') or '')[:60]
        linhas.append(_linha('J100', [
            'I', 'S', c['conta_id'][:60], cod_ref, (c['descricao'] or '')[:60], '',
            vd, vc, '', '', '', '', '', '', '',
        ]))
        total_dt += vd
        total_ct += vc
    if total_dt != total_ct:
        avisos.append(f'Balancete não fecha: débitos R$ {total_dt/100:,.2f} ≠ créditos R$ {total_ct/100:,.2f}.')

    # Partidas do diário (J930) no período escolhido.
    documentos = {}
    for m in sorted(mov, key=lambda x: (str(x['data']), x['documento_id'])):
        d = str(m['data'])
        if d < dt_ini or d > dt_fim:
            continue
        documentos.setdefault((d, m['documento_id']), []).append(m)
    for (d, doc), linhas_doc in sorted(documentos.items()):
        dv = sum(x['debito_centavos'] for x in linhas_doc)
        cv = sum(x['credito_centavos'] for x in linhas_doc)
        if dv != cv:
            avisos.append(f'Documento {doc} ({d}) desequilibrado: omitido do diário.')
            continue
        for i, m in enumerate(linhas_doc, 1):
            conta = contas_por_id.get(m['conta_id'], {})
            linhas.append(_linha('J930', [
                '', '', d.strftime('%d%m%Y') if hasattr(d, 'strftime') else d[8:10] + d[5:7] + d[:4],
                '999', m['documento_id'][:25] if m['documento_id'] else doc[:25],
                (m['historico'] or '')[:250] or f'Partida {i} do documento {doc}',
                (conta.get('cod_referencial') or '')[:60], conta.get('conta_id', '')[:60],
                str(m['debito_centavos'] or ''), str(m['credito_centavos'] or ''), '', 'I',
            ]))

    n = len(linhas) + 1
    linhas.append(_linha('9999', ['0', n]))
    return '\r\n'.join(linhas) + '\r\n', avisos
