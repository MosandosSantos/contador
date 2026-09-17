"""EFD-Contribuições: coleta de documentos fiscais e exportação mensal rascunho."""
import re
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, render_template, flash, redirect, Response
from flask_login import login_required
from psycopg2.extras import Json
from core.db import fetch, connection
from core.formularios import resposta_edicao
from core.efd_contribuicoes import calcular, gerar, CSTS_VALIDOS
from core.efd_icms_ipi import calcular as calcular_icms, gerar as gerar_icms, CST_ICMS_VALIDOS

efd = Blueprint('efd', __name__)
FORMAS = {}
TIPOS_DOC = {'saida': 'Saída', 'entrada': 'Entrada', 'servico': 'Serviço'}
LOCK = 20260924
PERIODO_RE = re.compile(r'^20[0-9]{2}-(0[1-9]|1[0-2])$')


def _centavos(campo, padrao=None):
    bruto = request.form.get(campo, '').strip()
    if not bruto and padrao is not None:
        return padrao
    try:
        valor = Decimal(bruto.replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Informe um valor válido em reais.')
    if not valor.is_finite() or not -10 ** 9 <= valor <= 10 ** 9 or valor.as_tuple().exponent < -2:
        raise ValueError('Use valor de até 1 bilhão com duas casas decimais.')
    return int(valor * 100)


def _aliq(campo):
    bruto = request.form.get(campo, '').strip()
    if not bruto:
        return '0'
    try:
        valor = Decimal(bruto.replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Informe uma alíquota válida.')
    if not valor.is_finite() or not 0 <= valor <= 100 or valor.as_tuple().exponent < -2:
        raise ValueError('Alíquota deve ficar entre 0 e 100 com até duas casas.')
    return str(valor)


def _periodo_padrao():
    linhas = fetch('SELECT DISTINCT periodo FROM nf_documentos ORDER BY periodo DESC LIMIT 1')
    if linhas:
        return linhas[0]['periodo']
    from datetime import date
    hoje = date.today()
    return f'{hoje.year}-{hoje.month:02d}'


def _participantes():
    return fetch('SELECT chave,documento,nome FROM participantes ORDER BY nome')


@efd.get('/nf')
@login_required
def nf():
    periodo = request.args.get('periodo', '')
    if not PERIODO_RE.fullmatch(periodo or ''):
        periodo = _periodo_padrao()
    documentos = fetch('''SELECT d.*,(SELECT COUNT(*) FROM nf_itens x WHERE x.documento_id=d.id) AS n_itens,
                                 (SELECT COALESCE(SUM(vl_item_centavos),0) FROM nf_itens x WHERE x.documento_id=d.id) AS total_itens
                          FROM nf_documentos d WHERE d.periodo=%s ORDER BY d.data_emissao,d.id''', (periodo,))
    contexto = dict(active='nf', title='NF e operações', periodo=periodo, tipos=TIPOS_DOC,
                    documentos=documentos, participantes=_participantes(), doc=None, itens=[])
    doc_id = request.args.get('doc', type=int)
    if doc_id:
        achado = next((d for d in documentos if d['id'] == doc_id), None)
        if not achado:
            achado = next((d for d in fetch('SELECT * FROM nf_documentos WHERE id=%s', (doc_id,))), None)
        if achado:
            contexto['doc'] = achado
            contexto['itens'] = fetch('SELECT * FROM nf_itens WHERE documento_id=%s ORDER BY id', (doc_id,))
    return render_template('nf.html', **contexto)


@efd.post('/nf/doc')
@login_required
def criar_doc():
    try:
        periodo = request.form.get('periodo', '').strip()
        if not PERIODO_RE.fullmatch(periodo or ''):
            raise ValueError('Período deve ser AAAA-MM.')
        tipo = request.form.get('tipo', '')
        if tipo not in TIPOS_DOC:
            raise ValueError('Selecione o tipo do documento.')
        participante = request.form.get('participante', '').strip()
        if not fetch('SELECT 1 FROM participantes WHERE chave=%s', (participante,)):
            raise ValueError('Cadastre o participante antes do documento.')
        numero = request.form.get('numero', '').strip()[:30]
        serie = request.form.get('serie', '').strip()[:5]
        data = request.form.get('data_emissao', '').strip()
        from datetime import date
        try:
            date.fromisoformat(data)
        except ValueError as erro:
            raise ValueError('Data de emissão inválida.') from erro
        if not data.startswith(periodo):
            raise ValueError('A data de emissão deve cair dentro do período informado.')
        valor = _centavos('valor_total', padrao=0)
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('''INSERT INTO nf_documentos(periodo,tipo,participante,numero,serie,data_emissao,valor_total_centavos)
                           VALUES(%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(periodo,tipo,participante,numero,serie) DO UPDATE
                           SET data_emissao=excluded.data_emissao,valor_total_centavos=excluded.valor_total_centavos,
                           atualizado=clock_timestamp() RETURNING id''',
                        (periodo, tipo, participante, numero, serie, data, valor))
            identificador = cur.fetchone()[0]
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('EFD: documento fiscal', Json({}), Json(dict(id=identificador, periodo=periodo, tipo=tipo, participante=participante, numero=numero, serie=serie, data=data, valor_centavos=valor))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/nf', erro=True)
    return resposta_edicao('Documento salvo.', f'/nf?periodo={periodo}&doc={identificador}')


@efd.post('/nf/doc/<int:identificador>/remover')
@login_required
def remover_doc(identificador):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(d) FROM nf_documentos d WHERE id=%s', (identificador,))
        antes = cur.fetchone()
        if antes:
            cur.execute('DELETE FROM nf_itens WHERE documento_id=%s', (identificador,))
            cur.execute('DELETE FROM nf_documentos WHERE id=%s', (identificador,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('EFD: documento fiscal removido', Json(dict(antes[0])), Json({})))
    return resposta_edicao('Documento removido.', '/nf')


@efd.post('/nf/item')
@login_required
def criar_item():
    try:
        doc_id = request.form.get('documento_id', type=int)
        doc = fetch('SELECT * FROM nf_documentos WHERE id=%s', (doc_id,))
        if not doc:
            raise ValueError('Documento não encontrado.')
        descricao = request.form.get('descricao', '').strip()[:200]
        if not descricao:
            raise ValueError('Informe a descrição do item.')
        cst_pis = request.form.get('cst_pis', '').strip()
        cst_cofins = request.form.get('cst_cofins', '').strip()
        if cst_pis not in CSTS_VALIDOS or cst_cofins not in CSTS_VALIDOS:
            raise ValueError('Selecione CST-PIS e CST-COFINS válidos.')
        cfop = ''.join(ch for ch in request.form.get('cfop', '').strip()[:4] if ch.isdigit())
        if cfop and len(cfop) != 4:
            raise ValueError('CFOP deve ter 4 dígitos.')
        dados = dict(documento_id=doc_id, descricao=descricao, cst_pis=cst_pis, cst_cofins=cst_cofins, cfop=cfop,
                     vl_item_centavos=_centavos('vl_item'),
                     vl_bc_pis_centavos=_centavos('vl_bc_pis', padrao=0), aliq_pis=_aliq('aliq_pis'), vl_pis_centavos=_centavos('vl_pis', padrao=0),
                     vl_bc_cofins_centavos=_centavos('vl_bc_cofins', padrao=0), aliq_cofins=_aliq('aliq_cofins'), vl_cofins_centavos=_centavos('vl_cofins', padrao=0),
                     ncm=''.join(ch for ch in request.form.get('ncm', '').strip()[:8] if ch.isdigit()),
                     cst_icms=request.form.get('cst_icms', '').strip(),
                     vl_bc_icms_centavos=_centavos('vl_bc_icms', padrao=0), aliq_icms=_aliq('aliq_icms'), vl_icms_centavos=_centavos('vl_icms', padrao=0),
                     vl_bc_ipi_centavos=_centavos('vl_bc_ipi', padrao=0), aliq_ipi=_aliq('aliq_ipi'), vl_ipi_centavos=_centavos('vl_ipi', padrao=0))
        if dados['cst_icms'] and dados['cst_icms'] not in CST_ICMS_VALIDOS:
            raise ValueError('CST-ICMS inválido.')
        if dados['ncm'] and len(dados['ncm']) != 8:
            raise ValueError('NCM deve ter 8 dígitos.')
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('''INSERT INTO nf_itens(documento_id,descricao,cst_pis,cst_cofins,cfop,vl_item_centavos,
                           vl_bc_pis_centavos,aliq_pis,vl_pis_centavos,vl_bc_cofins_centavos,aliq_cofins,vl_cofins_centavos,
                           ncm,cst_icms,vl_bc_icms_centavos,aliq_icms,vl_icms_centavos,vl_bc_ipi_centavos,aliq_ipi,vl_ipi_centavos)
                           VALUES(%(documento_id)s,%(descricao)s,%(cst_pis)s,%(cst_cofins)s,%(cfop)s,%(vl_item_centavos)s,
                           %(vl_bc_pis_centavos)s,%(aliq_pis)s,%(vl_pis_centavos)s,%(vl_bc_cofins_centavos)s,%(aliq_cofins)s,%(vl_cofins_centavos)s,
                           %(ncm)s,%(cst_icms)s,%(vl_bc_icms_centavos)s,%(aliq_icms)s,%(vl_icms_centavos)s,%(vl_bc_ipi_centavos)s,%(aliq_ipi)s,%(vl_ipi_centavos)s)
                           RETURNING id''', dados)
            identificador = cur.fetchone()[0]
            dados['id'] = identificador
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('EFD: item de documento', Json({}), Json(dados)))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), f'/nf?doc={request.form.get("documento_id", "")}', erro=True)
    return resposta_edicao('Item salvo.', f'/nf?doc={doc_id}')


@efd.post('/nf/item/<int:identificador>/remover')
@login_required
def remover_item(identificador):
    item = fetch('SELECT documento_id FROM nf_itens WHERE id=%s', (identificador,))
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(x) FROM nf_itens x WHERE id=%s', (identificador,))
        antes = cur.fetchone()
        if antes:
            cur.execute('DELETE FROM nf_itens WHERE id=%s', (identificador,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('EFD: item de documento removido', Json(dict(antes[0])), Json({})))
    destino = f"/nf?doc={item[0]['documento_id']}" if item else '/nf'
    return resposta_edicao('Item removido.', destino)


@efd.get('/efd-contribuicoes')
@login_required
def tela():
    contexto = _contexto_mes()
    return render_template('efd_contribuicoes.html', **contexto)


def _contexto_mes():
    periodo = request.args.get('periodo', '')
    if not PERIODO_RE.fullmatch(periodo or ''):
        periodo = _periodo_padrao()
    documentos = fetch('SELECT * FROM nf_documentos WHERE periodo=%s ORDER BY data_emissao,id', (periodo,))
    ids = [d['id'] for d in documentos]
    itens = fetch('SELECT * FROM nf_itens WHERE documento_id = ANY(%s) ORDER BY id', (ids,)) if ids else []
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    empresa = dict(empresa_row[0]) if empresa_row else {}
    numeros = None
    pendencias = []
    if not empresa:
        pendencias.append('Cadastre a empresa (Cadastros → Empresa).')
    else:
        try:
            numeros = calcular(documentos, itens)
        except ValueError as erro:
            pendencias.append(str(erro))
    return dict(active='efd-contribuicoes', title='EFD Contribuições', periodo=periodo, tipos=TIPOS_DOC,
                documentos=documentos, itens=itens, numeros=numeros, pendencias=pendencias)


@efd.get('/exportar/efd-contribuicoes')
@login_required
def exportar():
    contexto = _contexto_mes()
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    if not empresa_row:
        flash('Cadastre a empresa antes de exportar a EFD-Contribuições.', 'error')
        return redirect('/empresa')
    try:
        texto, avisos = gerar(dict(empresa_row[0]), _participantes(), contexto['documentos'],
                              contexto['itens'], contexto['periodo'])
    except ValueError as erro:
        flash(str(erro), 'error')
        return redirect('/efd-contribuicoes')
    for aviso in avisos[:4]:
        flash('Aviso: ' + aviso, 'error')
    if avisos:
        flash(f'EFD-Contribuições gerada com {len(avisos)} aviso(s). Confira no PVA da Receita antes de qualquer uso oficial.', 'error')
    else:
        flash('EFD-Contribuições rascunho gerada. Confira no PVA da Receita antes de qualquer uso oficial.', 'success')
    return Response(texto.encode('iso-8859-1', 'replace'), mimetype='text/plain',
                    headers={'Content-Disposition': f'attachment; filename="EFD_CONTRIBUICOES_{contexto["periodo"]}.txt"'})


@efd.get('/efd-icms-ipi')
@login_required
def tela_icms():
    contexto = _contexto_mes_icms()
    return render_template('efd_icms_ipi.html', **contexto)


def _contexto_mes_icms():
    periodo = request.args.get('periodo', '')
    if not PERIODO_RE.fullmatch(periodo or ''):
        periodo = _periodo_padrao()
    documentos = fetch('SELECT * FROM nf_documentos WHERE periodo=%s ORDER BY data_emissao,id', (periodo,))
    ids = [d['id'] for d in documentos]
    itens = fetch('SELECT * FROM nf_itens WHERE documento_id = ANY(%s) ORDER BY id', (ids,)) if ids else []
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    empresa = dict(empresa_row[0]) if empresa_row else {}
    numeros = None
    pendencias = []
    if not empresa:
        pendencias.append('Cadastre a empresa (Cadastros → Empresa).')
    else:
        try:
            numeros = calcular_icms(documentos, itens)
        except ValueError as erro:
            pendencias.append(str(erro))
    return dict(active='efd-icms-ipi', title='EFD ICMS/IPI', periodo=periodo, tipos=TIPOS_DOC,
                documentos=documentos, itens=itens, numeros=numeros, pendencias=pendencias)


@efd.get('/exportar/efd-icms-ipi')
@login_required
def exportar_icms():
    contexto = _contexto_mes_icms()
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    if not empresa_row:
        flash('Cadastre a empresa antes de exportar a EFD ICMS/IPI.', 'error')
        return redirect('/empresa')
    try:
        texto, avisos = gerar_icms(dict(empresa_row[0]), _participantes(), contexto['documentos'],
                                   contexto['itens'], contexto['periodo'])
    except ValueError as erro:
        flash(str(erro), 'error')
        return redirect('/efd-icms-ipi')
    for aviso in avisos[:4]:
        flash('Aviso: ' + aviso, 'error')
    if avisos:
        flash(f'EFD ICMS/IPI gerada com {len(avisos)} aviso(s). Confira no PVA da Receita antes de qualquer uso oficial.', 'error')
    else:
        flash('EFD ICMS/IPI rascunho gerada. Confira no PVA da Receita antes de qualquer uso oficial.', 'success')
    return Response(texto.encode('iso-8859-1', 'replace'), mimetype='text/plain',
                    headers={'Content-Disposition': f'attachment; filename="EFD_ICMS_IPI_{contexto["periodo"]}.txt"'})
