"""eSocial: empregados, rubricas, folha mensal e pacote de XMLs rascunho."""
import re
from datetime import date
from flask import Blueprint, request, render_template, flash, redirect, Response
from flask_login import login_required
from psycopg2.extras import Json
from core.db import fetch, connection
from core.formularios import resposta_edicao
from core.importacao import ler_tabela, celula, decimal_celula
from core.config_empresa import cpf_valido, formatar_cpf, normalizar_documento
from core.esocial import gerar, empacotar, CLAS_TRIB_VALIDAS

esocial = Blueprint('esocial', __name__)
LOCK = 20260925
PERIODO_RE = re.compile(r'^20[0-9]{2}-(0[1-9]|1[0-2])$')
CBO_RE = re.compile(r'^[0-9]{4,6}$')
NAT_JURIDICAS = {'2062': 'Sociedade empresária limitada', '2135': 'Empresário individual',
                 '2063': 'Sociedade empresária em nome coletivo', '3999': 'Outra'}


def _centavos(campo):
    return _centavos_valor(request.form.get(campo, ''))


def _centavos_valor(bruto):
    try:
        valor = decimal_celula(bruto)
    except ValueError:
        raise ValueError('Informe um valor válido em reais.')
    if valor is None:
        raise ValueError('Informe o valor em reais.')
    if not valor.is_finite() or not 0 <= valor <= 10 ** 9 or valor.as_tuple().exponent < -2:
        raise ValueError('Use valor de até 1 bilhão com duas casas decimais.')
    return int(valor * 100)


def _periodo_padrao():
    linhas = fetch('SELECT DISTINCT periodo FROM esocial_folha ORDER BY periodo DESC LIMIT 1')
    if linhas:
        return linhas[0]['periodo']
    hoje = date.today()
    return f'{hoje.year}-{hoje.month:02d}'


def _contexto():
    periodo = request.args.get('periodo', '')
    if not PERIODO_RE.fullmatch(periodo or ''):
        periodo = _periodo_padrao()
    parametros = next((x for x in fetch('SELECT * FROM esocial_parametros WHERE id=1')), None)
    empregados = fetch('SELECT * FROM esocial_empregados ORDER BY nome')
    rubricas = fetch('SELECT * FROM esocial_rubricas ORDER BY codigo')
    folha = fetch('''SELECT f.*,e.nome AS empregado_nome,r.codigo AS rubrica_codigo,r.descricao AS rubrica_descricao,r.tipo AS rubrica_tipo
                     FROM esocial_folha f JOIN esocial_empregados e ON e.id=f.empregado_id JOIN esocial_rubricas r ON r.id=f.rubrica_id
                     WHERE f.periodo=%s ORDER BY e.nome,r.codigo''', (periodo,))
    pendencias = []
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    if not empresa_row:
        pendencias.append('Cadastre a empresa (Cadastros → Empresa).')
    if not parametros:
        pendencias.append('Parametrize o empregador (classificação tributária).')
    return dict(active='esocial', title='eSocial', periodo=periodo, parametros=parametros,
                empregados=empregados, rubricas=rubricas, folha=folha, pendencias=pendencias,
                clas_tribut_validas=sorted(CLAS_TRIB_VALIDAS), nat_juridicas=NAT_JURIDICAS,
                empregado_por_id={e['id']: e for e in empregados})


@esocial.get('/esocial')
@login_required
def tela():
    return render_template('esocial.html', **_contexto())


@esocial.post('/esocial/parametros')
@login_required
def parametros():
    try:
        clas_tribut = request.form.get('clas_tribut', '').strip()
        nat_juridica = request.form.get('nat_juridica', '').strip()
        ind_deson = request.form.get('ind_deson', '0').strip()
        if clas_tribut not in CLAS_TRIB_VALIDAS:
            raise ValueError('Selecione uma classificação tributária válida.')
        if nat_juridica not in NAT_JURIDICAS:
            raise ValueError('Selecione uma natureza jurídica válida.')
        if ind_deson not in ('0', '1', '2'):
            raise ValueError('Indicativo de desoneração inválido.')
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('SELECT to_jsonb(p) FROM esocial_parametros p WHERE id=1')
            antes = cur.fetchone()
            cur.execute('''INSERT INTO esocial_parametros(id,clas_tribut,nat_juridica,ind_deson)
                           VALUES(1,%s,%s,%s)
                           ON CONFLICT(id) DO UPDATE SET clas_tribut=excluded.clas_tribut,
                           nat_juridica=excluded.nat_juridica,ind_deson=excluded.ind_deson,atualizado=clock_timestamp()''',
                        (clas_tribut, nat_juridica, ind_deson))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('eSocial: parâmetros do empregador', Json(dict(antes[0]) if antes else {}), Json(dict(clas_tribut=clas_tribut, nat_juridica=nat_juridica, ind_deson=ind_deson))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/esocial', erro=True)
    return resposta_edicao('Parâmetros do eSocial salvos.', '/esocial')


@esocial.post('/esocial/empregado')
@login_required
def empregado():
    try:
        nome = request.form.get('nome', '').strip()[:200]
        if not nome:
            raise ValueError('Informe o nome do empregado.')
        cpf = normalizar_documento(request.form.get('cpf', ''))
        if not cpf:
            raise ValueError('Informe o CPF do empregado.')
        nis = ''.join(ch for ch in request.form.get('nis', '').strip()[:11] if ch.isdigit())
        cargo = request.form.get('cargo', '').strip()[:120]
        cbo = request.form.get('cbo', '').strip()
        if cbo and not CBO_RE.fullmatch(cbo):
            raise ValueError('CBO deve ter 4 a 6 dígitos.')
        data = request.form.get('data_admissao', '').strip()
        try:
            date.fromisoformat(data)
        except ValueError as erro:
            raise ValueError('Data de admissão inválida.') from erro
        salario = _centavos('salario')
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('SELECT 1 FROM esocial_empregados WHERE cpf=%s', (cpf,))
            if cur.fetchone():
                raise ValueError('Já existe empregado cadastrado com esse CPF.')
            cur.execute('''INSERT INTO esocial_empregados(nome,cpf,nis,cargo,cbo,data_admissao,salario_centavos)
                           VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (nome, cpf, nis, cargo, cbo, data, salario))
            identificador = cur.fetchone()[0]
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('eSocial: empregado', Json({}), Json(dict(id=identificador, nome=nome, cpf=cpf, nis=nis, data=data, salario_centavos=salario))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/esocial', erro=True)
    return resposta_edicao('Empregado salvo.', '/esocial')


@esocial.post('/esocial/empregado/<int:identificador>/remover')
@login_required
def remover_empregado(identificador):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(e) FROM esocial_empregados e WHERE id=%s', (identificador,))
        antes = cur.fetchone()
        if antes:
            cur.execute('DELETE FROM esocial_folha WHERE empregado_id=%s', (identificador,))
            cur.execute('DELETE FROM esocial_empregados WHERE id=%s', (identificador,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('eSocial: empregado removido', Json(dict(antes[0])), Json({})))
    return resposta_edicao('Empregado removido.', '/esocial')


@esocial.post('/esocial/rubrica')
@login_required
def rubrica():
    try:
        codigo = request.form.get('codigo', '').strip()
        if not re.fullmatch(r'[A-Za-z0-9]{1,30}', codigo):
            raise ValueError('Código da rubrica: até 30 caracteres alfanuméricos.')
        descricao = request.form.get('descricao', '').strip()[:200]
        if not descricao:
            raise ValueError('Informe a descrição da rubrica.')
        tipo = request.form.get('tipo', '')
        if tipo not in ('provento', 'desconto'):
            raise ValueError('Selecione o tipo da rubrica.')
        incid_inss = request.form.get('incid_inss') == '1'
        incid_irrf = request.form.get('incid_irrf') == '1'
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('SELECT 1 FROM esocial_rubricas WHERE codigo=%s', (codigo,))
            if cur.fetchone():
                raise ValueError('Já existe rubrica com esse código.')
            cur.execute('''INSERT INTO esocial_rubricas(codigo,descricao,tipo,incid_inss,incid_irrf)
                           VALUES(%s,%s,%s,%s,%s) RETURNING id''', (codigo, descricao, tipo, incid_inss, incid_irrf))
            identificador = cur.fetchone()[0]
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('eSocial: rubrica', Json({}), Json(dict(id=identificador, codigo=codigo, tipo=tipo, incid_inss=incid_inss, incid_irrf=incid_irrf))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/esocial', erro=True)
    return resposta_edicao('Rubrica salva.', '/esocial')


@esocial.post('/esocial/rubrica/<int:identificador>/remover')
@login_required
def remover_rubrica(identificador):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(r) FROM esocial_rubricas r WHERE id=%s', (identificador,))
        antes = cur.fetchone()
        if antes:
            cur.execute('SELECT 1 FROM esocial_folha WHERE rubrica_id=%s LIMIT 1', (identificador,))
            if cur.fetchone():
                return resposta_edicao('Remova os lançamentos de folha que usam a rubrica antes de excluí-la.', '/esocial', erro=True)
            cur.execute('DELETE FROM esocial_rubricas WHERE id=%s', (identificador,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('eSocial: rubrica removida', Json(dict(antes[0])), Json({})))
    return resposta_edicao('Rubrica removida.', '/esocial')


@esocial.post('/esocial/folha')
@login_required
def folha():
    try:
        periodo = request.form.get('periodo', '').strip()
        if not PERIODO_RE.fullmatch(periodo or ''):
            raise ValueError('Período deve ser AAAA-MM.')
        empregado_id = request.form.get('empregado_id', type=int)
        if not fetch('SELECT 1 FROM esocial_empregados WHERE id=%s', (empregado_id,)):
            raise ValueError('Cadastre o empregado antes do lançamento.')
        rubrica_id = request.form.get('rubrica_id', type=int)
        if not fetch('SELECT 1 FROM esocial_rubricas WHERE id=%s', (rubrica_id,)):
            raise ValueError('Cadastre a rubrica antes do lançamento.')
        valor = _centavos('valor')
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('''INSERT INTO esocial_folha(periodo,empregado_id,rubrica_id,valor_centavos)
                           VALUES(%s,%s,%s,%s)
                           ON CONFLICT(periodo,empregado_id,rubrica_id) DO UPDATE
                           SET valor_centavos=excluded.valor_centavos RETURNING id''', (periodo, empregado_id, rubrica_id, valor))
            identificador = cur.fetchone()[0]
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('eSocial: folha', Json({}), Json(dict(id=identificador, periodo=periodo, empregado_id=empregado_id, rubrica_id=rubrica_id, valor_centavos=valor))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/esocial', erro=True)
    return resposta_edicao('Lançamento de folha salvo.', f'/esocial?periodo={periodo}')


def _planilha_folha(linhas):
    """Valida a planilha (periodo, cpf ou nome, rubrica, valor) e resolve os vínculos."""
    colunas = set().union(*(set(l) for l in linhas))
    faltando = {'periodo', 'rubrica', 'valor'} - colunas
    if faltando or not ({'cpf', 'empregado', 'nome'} & colunas):
        raise ValueError('Use as colunas periodo, cpf (ou nome), rubrica e valor. Baixe o modelo em /modelo/folha-esocial.')
    empregados = {}
    for e in fetch('SELECT id,cpf,nome FROM esocial_empregados'):
        empregados[e['cpf']] = e['id']
        digitos = ''.join(c for c in e['cpf'] if c.isdigit())
        empregados[digitos] = e['id']
        empregados[e['nome'].casefold()] = e['id']
    rubricas = {}
    for r in fetch('SELECT id,codigo FROM esocial_rubricas'):
        rubricas[r['codigo']] = r['id']
        rubricas[r['codigo'].casefold()] = r['id']
    lancamentos = {}
    for i, ln in enumerate(linhas, start=2):
        prefixo = f'Linha {i}: '
        periodo = celula(ln.get('periodo'))
        if not PERIODO_RE.fullmatch(periodo):
            raise ValueError(prefixo + 'período deve ser AAAA-MM.')
        bruto = celula(ln.get('cpf') or ln.get('empregado') or ln.get('nome'))
        digitos = ''.join(c for c in bruto if c.isdigit())
        empregado_id = empregados.get(digitos) if digitos else None
        if not empregado_id and bruto:
            empregado_id = empregados.get(bruto.casefold())
        if not empregado_id:
            raise ValueError(prefixo + 'empregado não encontrado pelo CPF ou nome: ' + bruto[:60])
        codigo = celula(ln.get('rubrica') or ln.get('codigo'))
        rubrica_id = rubricas.get(codigo) or rubricas.get(codigo.casefold())
        if not rubrica_id:
            raise ValueError(prefixo + 'rubrica não encontrada pelo código: ' + codigo[:30])
        try:
            centavos = _centavos_valor(ln.get('valor'))
        except ValueError as erro:
            raise ValueError(prefixo + str(erro)) from erro
        lancamentos[(periodo, empregado_id, rubrica_id)] = centavos
    return lancamentos, next(iter(lancamentos))[0]


@esocial.post('/esocial/folha/importar')
@login_required
def importar_folha():
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        return resposta_edicao('Escolha o arquivo CSV ou XLSX com a folha.', '/esocial', erro=True)
    bruto = arquivo.read()
    if len(bruto) > 12 * 1024 * 1024:
        return resposta_edicao('Arquivo maior que 12 MB.', '/esocial', erro=True)
    try:
        linhas = ler_tabela(bruto, arquivo.filename)
        if not linhas or len(linhas) > 5000:
            raise ValueError('Envie de 1 a 5.000 linhas.')
        lancamentos, periodo_alvo = _planilha_folha(linhas)
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            for (periodo, empregado_id, rubrica_id), centavos in sorted(lancamentos.items()):
                cur.execute('''INSERT INTO esocial_folha(periodo,empregado_id,rubrica_id,valor_centavos)
                               VALUES(%s,%s,%s,%s)
                               ON CONFLICT(periodo,empregado_id,rubrica_id) DO UPDATE
                               SET valor_centavos=excluded.valor_centavos''', (periodo, empregado_id, rubrica_id, centavos))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('eSocial: importação de folha', Json({}), Json(dict(linhas=len(linhas), lancamentos=len(lancamentos), periodo=periodo_alvo))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/esocial', erro=True)
    return resposta_edicao(f'Importação concluída: {len(lancamentos)} lançamento(s). Lançamentos já existentes no período tiveram o valor atualizado.',
                           f'/esocial?periodo={periodo_alvo}')


@esocial.post('/esocial/folha/<int:identificador>/remover')
@login_required
def remover_folha(identificador):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(f) FROM esocial_folha f WHERE id=%s', (identificador,))
        antes = cur.fetchone()
        if antes:
            cur.execute('DELETE FROM esocial_folha WHERE id=%s', (identificador,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('eSocial: folha removida', Json(dict(antes[0])), Json({})))
    return resposta_edicao('Lançamento removido.', '/esocial')


@esocial.get('/exportar/esocial')
@login_required
def exportar():
    contexto = _contexto()
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    if not empresa_row:
        flash('Cadastre a empresa antes de exportar o eSocial.', 'error')
        return redirect('/empresa')
    try:
        arquivos, avisos = gerar(dict(empresa_row[0]), contexto['parametros'], contexto['empregados'],
                                 contexto['rubricas'], contexto['folha'], contexto['periodo'])
    except ValueError as erro:
        flash(str(erro), 'error')
        return redirect('/esocial')
    for aviso in avisos[:4]:
        flash('Aviso: ' + aviso, 'error')
    if avisos:
        flash(f'Pacote eSocial gerado com {len(avisos)} aviso(s). Rascunho em produção restrita: confira no AVS antes de qualquer uso.', 'error')
    else:
        flash('Pacote eSocial rascunho gerado (produção restrita). Confira no AVS antes de qualquer uso oficial.', 'success')
    return Response(empacotar(arquivos), mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="esocial_rascunho_{contexto["periodo"]}.zip"'})
