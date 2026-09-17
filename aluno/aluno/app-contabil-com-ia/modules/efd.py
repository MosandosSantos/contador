"""EFD-Contribuições: coleta de documentos fiscais e exportação mensal rascunho."""
import re
from datetime import date
from flask import Blueprint, request, render_template, flash, redirect, Response
from flask_login import login_required
from psycopg2.extras import Json
from core.db import fetch, connection
from core.formularios import resposta_edicao
from core.importacao import ler_tabela, celula, decimal_celula
from core.config_empresa import normalizar_documento
from core.efd_contribuicoes import calcular, gerar, CSTS_VALIDOS
from core.efd_icms_ipi import calcular as calcular_icms, gerar as gerar_icms, CST_ICMS_VALIDOS

efd = Blueprint('efd', __name__)
FORMAS = {}
TIPOS_DOC = {'saida': 'Saída', 'entrada': 'Entrada', 'servico': 'Serviço'}
LOCK = 20260924
PERIODO_RE = re.compile(r'^20[0-9]{2}-(0[1-9]|1[0-2])$')
COLUNAS_NF_MINIMAS = {'periodo', 'tipo', 'participante', 'numero', 'data_emissao', 'descricao', 'cst_pis', 'cst_cofins', 'vl_item'}


def _centavos_de(bruto, padrao=None):
    """Valor monetário (célula ou campo) em centavos; None/vazio cai no padrão."""
    try:
        valor = decimal_celula(bruto)
    except ValueError:
        raise ValueError('Informe um valor válido em reais.')
    if valor is None:
        if padrao is not None:
            return padrao
        raise ValueError('Informe o valor em reais.')
    if not valor.is_finite() or not -10 ** 9 <= valor <= 10 ** 9 or valor.as_tuple().exponent < -2:
        raise ValueError('Use valor de até 1 bilhão com duas casas decimais.')
    return int(valor * 100)


def _aliq_de(bruto):
    try:
        valor = decimal_celula(bruto)
    except ValueError:
        raise ValueError('Informe uma alíquota válida.')
    if valor is None:
        return '0'
    if not valor.is_finite() or not 0 <= valor <= 100 or valor.as_tuple().exponent < -2:
        raise ValueError('Alíquota deve ficar entre 0 e 100 com até duas casas.')
    return str(valor)


def _centavos(campo, padrao=None):
    return _centavos_de(request.form.get(campo, '').strip(), padrao)


def _aliq(campo):
    return _aliq_de(request.form.get(campo, '').strip())


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


def _cst_planilha(valor):
    texto = celula(valor)
    if len(texto) == 1 and texto.isdigit():
        texto = '0' + texto
    return texto


def _planilha_nf(linhas):
    """Valida a planilha (uma linha por item) e agrupa por documento fiscal."""
    colunas = set().union(*(set(l) for l in linhas))
    faltando = COLUNAS_NF_MINIMAS - colunas
    if faltando:
        raise ValueError('Faltam colunas no arquivo: ' + ', '.join(sorted(faltando)) + '. Baixe o modelo em /modelo/nf.')
    chaves = {}
    for p in fetch('SELECT chave,documento,nome FROM participantes'):
        chaves[p['chave'].casefold()] = p['chave']
        chaves[p['nome'].casefold()] = p['chave']
        if p['documento']:
            chaves[p['documento'].casefold()] = p['chave']
            digitos = ''.join(c for c in p['documento'] if c.isdigit())
            if digitos:
                chaves[digitos] = p['chave']
    documentos = {}
    total_itens = 0
    for i, ln in enumerate(linhas, start=2):
        prefixo = f'Linha {i}: '
        periodo = celula(ln.get('periodo'))
        if not PERIODO_RE.fullmatch(periodo):
            raise ValueError(prefixo + 'período deve ser AAAA-MM.')
        tipo = celula(ln.get('tipo')).casefold()
        if tipo not in TIPOS_DOC:
            raise ValueError(prefixo + 'tipo deve ser saida, entrada ou servico.')
        bruto = celula(ln.get('participante'))
        digitos = ''.join(c for c in bruto if c.isdigit())
        participante = chaves.get(bruto.casefold()) or (chaves.get(digitos) if digitos else None)
        if not participante:
            raise ValueError(prefixo + 'participante não encontrado no cadastro: ' + bruto[:60])
        numero = celula(ln.get('numero'))[:30]
        if not numero:
            raise ValueError(prefixo + 'informe o número do documento.')
        serie = celula(ln.get('serie'))[:5]
        data = celula(ln.get('data_emissao'))
        try:
            date.fromisoformat(data)
        except ValueError as erro:
            raise ValueError(prefixo + 'data de emissão inválida (AAAA-MM-DD).') from erro
        if not data.startswith(periodo):
            raise ValueError(prefixo + 'a data de emissão deve cair dentro do período.')
        descricao = celula(ln.get('descricao'))[:200]
        if not descricao:
            raise ValueError(prefixo + 'informe a descrição do item.')
        cst_pis = _cst_planilha(ln.get('cst_pis'))
        cst_cofins = _cst_planilha(ln.get('cst_cofins'))
        if cst_pis not in CSTS_VALIDOS or cst_cofins not in CSTS_VALIDOS:
            raise ValueError(prefixo + 'CST-PIS/COFINS inválido (código com 2 dígitos).')
        cfop = ''.join(c for c in celula(ln.get('cfop'))[:4] if c.isdigit())
        if cfop and len(cfop) != 4:
            raise ValueError(prefixo + 'CFOP deve ter 4 dígitos.')
        ncm = ''.join(c for c in celula(ln.get('ncm'))[:8] if c.isdigit())
        if ncm and len(ncm) != 8:
            raise ValueError(prefixo + 'NCM deve ter 8 dígitos.')
        cst_icms = celula(ln.get('cst_icms'))
        if cst_icms and cst_icms not in CST_ICMS_VALIDOS:
            raise ValueError(prefixo + 'CST-ICMS inválido.')
        try:
            item = dict(descricao=descricao, cst_pis=cst_pis, cst_cofins=cst_cofins, cfop=cfop,
                        vl_item_centavos=_centavos_de(ln.get('vl_item')),
                        vl_bc_pis_centavos=_centavos_de(ln.get('vl_bc_pis'), padrao=0), aliq_pis=_aliq_de(ln.get('aliq_pis')),
                        vl_pis_centavos=_centavos_de(ln.get('vl_pis'), padrao=0),
                        vl_bc_cofins_centavos=_centavos_de(ln.get('vl_bc_cofins'), padrao=0), aliq_cofins=_aliq_de(ln.get('aliq_cofins')),
                        vl_cofins_centavos=_centavos_de(ln.get('vl_cofins'), padrao=0), ncm=ncm, cst_icms=cst_icms,
                        vl_bc_icms_centavos=_centavos_de(ln.get('vl_bc_icms'), padrao=0), aliq_icms=_aliq_de(ln.get('aliq_icms')),
                        vl_icms_centavos=_centavos_de(ln.get('vl_icms'), padrao=0),
                        vl_bc_ipi_centavos=_centavos_de(ln.get('vl_bc_ipi'), padrao=0), aliq_ipi=_aliq_de(ln.get('aliq_ipi')),
                        vl_ipi_centavos=_centavos_de(ln.get('vl_ipi'), padrao=0))
        except ValueError as erro:
            raise ValueError(prefixo + str(erro)) from erro
        chave_doc = (periodo, tipo, participante, numero, serie)
        doc = documentos.get(chave_doc)
        if not doc:
            doc = dict(data_emissao=data, valor_total_centavos=None, itens=[])
            documentos[chave_doc] = doc
        elif doc['data_emissao'] != data:
            raise ValueError(prefixo + 'documento repetido com datas de emissão diferentes.')
        if ln.get('valor_total') is not None and celula(ln.get('valor_total')):
            doc['valor_total_centavos'] = _centavos_de(ln.get('valor_total'))
        doc['itens'].append(item)
        total_itens += 1
    for doc in documentos.values():
        if doc['valor_total_centavos'] is None:
            doc['valor_total_centavos'] = sum(x['vl_item_centavos'] for x in doc['itens'])
    return documentos, total_itens, next(iter(documentos))[0]


@efd.post('/nf/importar')
@login_required
def importar_nf():
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        return resposta_edicao('Escolha o arquivo CSV ou XLSX com as notas.', '/nf', erro=True)
    bruto = arquivo.read()
    if len(bruto) > 12 * 1024 * 1024:
        return resposta_edicao('Arquivo maior que 12 MB.', '/nf', erro=True)
    try:
        linhas = ler_tabela(bruto, arquivo.filename)
        if not linhas or len(linhas) > 5000:
            raise ValueError('Envie de 1 a 5.000 linhas de itens.')
        documentos, total_itens, periodo_alvo = _planilha_nf(linhas)
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            for chave_doc, doc in sorted(documentos.items()):
                periodo, tipo, participante, numero, serie = chave_doc
                cur.execute('''INSERT INTO nf_documentos(periodo,tipo,participante,numero,serie,data_emissao,valor_total_centavos)
                               VALUES(%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(periodo,tipo,participante,numero,serie) DO UPDATE
                               SET data_emissao=excluded.data_emissao,valor_total_centavos=excluded.valor_total_centavos,
                               atualizado=clock_timestamp() RETURNING id''',
                            chave_doc + (doc['data_emissao'], doc['valor_total_centavos']))
                doc_id = cur.fetchone()[0]
                cur.execute('DELETE FROM nf_itens WHERE documento_id=%s', (doc_id,))
                cur.executemany('''INSERT INTO nf_itens(documento_id,descricao,cst_pis,cst_cofins,cfop,vl_item_centavos,
                                   vl_bc_pis_centavos,aliq_pis,vl_pis_centavos,vl_bc_cofins_centavos,aliq_cofins,vl_cofins_centavos,
                                   ncm,cst_icms,vl_bc_icms_centavos,aliq_icms,vl_icms_centavos,vl_bc_ipi_centavos,aliq_ipi,vl_ipi_centavos)
                                   VALUES(%(documento_id)s,%(descricao)s,%(cst_pis)s,%(cst_cofins)s,%(cfop)s,%(vl_item_centavos)s,
                                   %(vl_bc_pis_centavos)s,%(aliq_pis)s,%(vl_pis_centavos)s,%(vl_bc_cofins_centavos)s,%(aliq_cofins)s,%(vl_cofins_centavos)s,
                                   %(ncm)s,%(cst_icms)s,%(vl_bc_icms_centavos)s,%(aliq_icms)s,%(vl_icms_centavos)s,%(vl_bc_ipi_centavos)s,%(aliq_ipi)s,%(vl_ipi_centavos)s)''',
                                [dict(it, documento_id=doc_id) for it in doc['itens']])
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('EFD: importação de documentos', Json({}), Json(dict(documentos=len(documentos), itens=total_itens, periodo=periodo_alvo))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/nf', erro=True)
    mensagem = (f'Importação concluída: {len(documentos)} documento(s) e {total_itens} item(ns). '
                'Itens de documentos reenviados foram substituídos pelos do arquivo.')
    return resposta_edicao(mensagem, f'/nf?periodo={periodo_alvo}')


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
