"""ECF fiscal: parametrização anual, Parte B, conciliação e exportação rascunho."""
from datetime import date
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, render_template, flash, redirect, Response
from flask_login import login_required
from psycopg2.extras import Json
from core.db import fetch, connection
from core.formularios import resposta_edicao
from core.ecf import calcular, gerar_ecf

ecf = Blueprint('ecf', __name__)
FORMAS = {'trimestral': 'Trimestral', 'mensal_estimativa': 'Mensal (estimativa mensal)'}
LOCK = 20260923


def _centavos(campo):
    try:
        valor = Decimal(request.form.get(campo, '').replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Informe um valor válido em reais.')
    if not valor.is_finite() or not -10 ** 9 <= valor <= 10 ** 9 or valor.as_tuple().exponent < -2:
        raise ValueError('Use valor de até 1 bilhão com duas casas decimais.')
    return int(valor * 100)


def _pct(campo):
    try:
        valor = Decimal(request.form.get(campo, '').replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Percentual de presunção inválido.')
    if not valor.is_finite() or not 0 <= valor <= 100 or valor.as_tuple().exponent < -2:
        raise ValueError('Percentual de presunção deve ficar entre 0 e 100 com até duas casas.')
    return str(valor)


def _contexto():
    mov = fetch('SELECT conta_id,data,debito_centavos,credito_centavos,tipo FROM lancamentos ORDER BY data')
    contas = fetch('SELECT conta_id,descricao,grupo,analitica,nivel,cod_referencial,linha_dre FROM contas ORDER BY ordem,conta_id')
    anos = {d['data'].year for d in mov} | {x['ano'] for x in fetch('SELECT ano FROM ecf_parametros')} | {date.today().year}
    ano = request.args.get('ano', type=int)
    ano = ano if ano in anos else max(anos)
    parametros = next((x for x in fetch('SELECT * FROM ecf_parametros WHERE ano=%s', (ano,))), None)
    contas_pb = fetch('SELECT * FROM ecf_contas_pb ORDER BY codigo')
    lancamentos = fetch('SELECT l.*,p.descricao AS conta_pb_descricao FROM ecf_lancamentos l JOIN ecf_contas_pb p ON p.codigo=l.conta_pb WHERE l.periodo LIKE %s ORDER BY l.periodo,l.data,l.id', (f'{ano}%',))
    conciliacao = fetch('SELECT * FROM ecf_conciliacao ORDER BY ordem,id')
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    empresa = dict(empresa_row[0]) if empresa_row else {}
    numeros = None
    if empresa:
        try:
            numeros = calcular(empresa, contas, mov, parametros, contas_pb, lancamentos, conciliacao, ano)
        except ValueError:
            numeros = None
    pendencias = []
    if not empresa:
        pendencias.append('Cadastre a empresa (Cadastros → Empresa).')
    elif not (empresa.get('ie') and empresa.get('cod_mun')):
        pendencias.append('Informe IE e código IBGE do município da empresa.')
    if not parametros:
        pendencias.append(f'Parametrize o ano-calendário {ano}.')
    return dict(active='ecf', title='ECF fiscal', ano=ano, anos=sorted(anos), parametros=parametros,
                formas=FORMAS, contas_pb=contas_pb, lancamentos=lancamentos, conciliacao=conciliacao,
                numeros=numeros, pendencias=pendencias,
                contas_resultado=[c for c in contas if c.get('grupo') == 'resultado' and c.get('analitica')])


@ecf.get('/ecf')
@login_required
def tela():
    return render_template('ecf.html', **_contexto())


@ecf.post('/ecf/parametros')
@login_required
def parametros():
    try:
        ano = request.form.get('ano', type=int)
        forma = request.form.get('forma_tributacao', '')
        if not ano or not 2000 <= ano <= 2100:
            raise ValueError('Ano-calendário inválido.')
        if forma not in FORMAS:
            raise ValueError('Selecione a forma de tributação.')
        dados = dict(ano=ano, forma_tributacao=forma, pct_presuncao_irpj=_pct('pct_presuncao_irpj'),
                     pct_presuncao_csll=_pct('pct_presuncao_csll'), adicional=request.form.get('adicional') == '1')
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('SELECT to_jsonb(p) FROM ecf_parametros p WHERE ano=%s', (ano,))
            antes = cur.fetchone()
            cur.execute('''INSERT INTO ecf_parametros(ano,forma_tributacao,pct_presuncao_irpj,pct_presuncao_csll,adicional)
                           VALUES(%(ano)s,%(forma_tributacao)s,%(pct_presuncao_irpj)s,%(pct_presuncao_csll)s,%(adicional)s)
                           ON CONFLICT(ano) DO UPDATE SET forma_tributacao=excluded.forma_tributacao,
                           pct_presuncao_irpj=excluded.pct_presuncao_irpj,pct_presuncao_csll=excluded.pct_presuncao_csll,
                           adicional=excluded.adicional,atualizado=clock_timestamp()''', dados)
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('ECF: parâmetros', Json(dict(antes[0]) if antes else {}), Json(dados)))
    except (ValueError, TypeError, InvalidOperation) as erro:
        return resposta_edicao(str(erro), '/ecf', erro=True)
    return resposta_edicao('Parâmetros do ECF salvos.', f'/ecf?ano={dados["ano"]}')


@ecf.post('/ecf/conta-pb')
@login_required
def conta_pb():
    import re
    try:
        codigo = request.form.get('codigo', '').strip()
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,30}', codigo):
            raise ValueError('Código da conta Parte B: até 30 caracteres (letras, números, . _ -).')
        descricao = request.form.get('descricao', '').strip()[:200]
        if not descricao:
            raise ValueError('Informe a descrição da conta Parte B.')
        tipo = request.form.get('tipo', '')
        if tipo not in ('A', 'B'):
            raise ValueError('Tipo deve ser A (Parte A) ou B (Parte B).')
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('SELECT to_jsonb(p) FROM ecf_contas_pb p WHERE codigo=%s', (codigo,))
            antes = cur.fetchone()
            cur.execute('''INSERT INTO ecf_contas_pb(codigo,descricao,tipo) VALUES(%s,%s,%s)
                           ON CONFLICT(codigo) DO UPDATE SET descricao=excluded.descricao,tipo=excluded.tipo''',
                        (codigo, descricao, tipo))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('ECF: conta Parte B', Json(dict(antes[0]) if antes else {}), Json(dict(codigo=codigo, descricao=descricao, tipo=tipo))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/ecf', erro=True)
    return resposta_edicao('Conta Parte B salva.', '/ecf')


@ecf.post('/ecf/conta-pb/<codigo>/remover')
@login_required
def remover_conta_pb(codigo):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(p) FROM ecf_contas_pb p WHERE codigo=%s', (codigo,))
        antes = cur.fetchone()
        if antes:
            cur.execute('SELECT 1 FROM ecf_lancamentos WHERE conta_pb=%s LIMIT 1', (codigo,))
            if cur.fetchone():
                return resposta_edicao('Remova os lançamentos vinculados antes de excluir a conta.', '/ecf', erro=True)
            cur.execute('DELETE FROM ecf_contas_pb WHERE codigo=%s', (codigo,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('ECF: conta Parte B removida', Json(dict(antes[0])), Json({})))
    return resposta_edicao('Conta Parte B removida.', '/ecf')


@ecf.post('/ecf/lancamento')
@login_required
def lancamento():
    import re
    try:
        periodo = request.form.get('periodo', '').strip()
        if not re.fullmatch(r'20[0-9]{2}T[1-4]', periodo):
            raise ValueError('Período deve ser AAAATn (ex.: 2026T1).')
        conta_pb = request.form.get('conta_pb', '').strip()
        if not fetch('SELECT 1 FROM ecf_contas_pb WHERE codigo=%s', (conta_pb,)):
            raise ValueError('Cadastre a conta Parte B antes do lançamento.')
        tipo = request.form.get('tipo', '')
        if tipo not in ('A', 'B', 'C'):
            raise ValueError('Tipo do lançamento deve ser A (adição), B (exclusão) ou C (compensação).')
        data = request.form.get('data', '').strip()
        try:
            date.fromisoformat(data)
        except ValueError as erro:
            raise ValueError('Data inválida.') from erro
        valor = _centavos('valor')
        historico = request.form.get('historico', '').strip()[:500]
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('''INSERT INTO ecf_lancamentos(periodo,conta_pb,tipo,data,valor_centavos,historico)
                           VALUES(%s,%s,%s,%s,%s,%s) RETURNING id''', (periodo, conta_pb, tipo, data, valor, historico))
            identificador = cur.fetchone()[0]
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('ECF: lançamento Parte B', Json({}), Json(dict(id=identificador, periodo=periodo, conta_pb=conta_pb, tipo=tipo, data=data, valor_centavos=valor, historico=historico))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/ecf', erro=True)
    return resposta_edicao('Lançamento da Parte B salvo.', '/ecf')


@ecf.post('/ecf/lancamento/<int:identificador>/remover')
@login_required
def remover_lancamento(identificador):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(l) FROM ecf_lancamentos l WHERE id=%s', (identificador,))
        antes = cur.fetchone()
        if antes:
            cur.execute('DELETE FROM ecf_lancamentos WHERE id=%s', (identificador,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('ECF: lançamento Parte B removido', Json(dict(antes[0])), Json({})))
    return resposta_edicao('Lançamento removido.', '/ecf')


@ecf.post('/ecf/conciliacao')
@login_required
def conciliacao():
    try:
        conta_id = request.form.get('conta_id', '').strip()
        if not fetch('SELECT 1 FROM contas WHERE conta_id=%s', (conta_id,)):
            raise ValueError('Escolha uma conta contábil cadastrada.')
        valor = _centavos('valor')
        historico = request.form.get('historico', '').strip()[:500]
        ordem = request.form.get('ordem', type=int) or 100
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            cur.execute('''INSERT INTO ecf_conciliacao(conta_id,valor_centavos,historico,ordem) VALUES(%s,%s,%s,%s) RETURNING id''',
                        (conta_id, valor, historico, ordem))
            identificador = cur.fetchone()[0]
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                        ('ECF: conciliação fiscal', Json({}), Json(dict(id=identificador, conta_id=conta_id, valor_centavos=valor, historico=historico))))
    except (ValueError, TypeError) as erro:
        return resposta_edicao(str(erro), '/ecf', erro=True)
    return resposta_edicao('Item de conciliação salvo.', '/ecf')


@ecf.post('/ecf/conciliacao/<int:identificador>/remover')
@login_required
def remover_conciliacao(identificador):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        cur.execute('SELECT to_jsonb(c) FROM ecf_conciliacao c WHERE id=%s', (identificador,))
        antes = cur.fetchone()
        if antes:
            cur.execute('DELETE FROM ecf_conciliacao WHERE id=%s', (identificador,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', ('ECF: conciliação fiscal removida', Json(dict(antes[0])), Json({})))
    return resposta_edicao('Item de conciliação removido.', '/ecf')


@ecf.get('/exportar/ecf')
@login_required
def exportar():
    contexto = _contexto()
    empresa_row = fetch('SELECT * FROM empresa WHERE id=1')
    if not empresa_row:
        flash('Cadastre a empresa antes de exportar o ECF.', 'error')
        return redirect('/empresa')
    try:
        texto, avisos = gerar_ecf(dict(empresa_row[0]),
                                  fetch('SELECT conta_id,descricao,grupo,analitica,nivel,cod_referencial,linha_dre FROM contas ORDER BY ordem,conta_id'),
                                  fetch('SELECT documento_id,data,conta_id,debito_centavos,credito_centavos,tipo,historico FROM lancamentos ORDER BY data,documento_id'),
                                  fetch('SELECT documento,nome FROM participantes ORDER BY nome'),
                                  contexto['parametros'], contexto['contas_pb'], contexto['lancamentos'],
                                  contexto['conciliacao'], contexto['ano'])
    except ValueError as erro:
        flash(str(erro), 'error')
        return redirect('/ecf')
    for aviso in avisos[:4]:
        flash('Aviso: ' + aviso, 'error')
    if avisos:
        flash(f'ECF gerada com {len(avisos)} aviso(s). Confira no PVA da Receita antes de qualquer uso oficial.', 'error')
    else:
        flash('ECF rascunho gerada. Confira no PVA da Receita antes de qualquer uso oficial.', 'success')
    return Response(texto.encode('iso-8859-1', 'replace'), mimetype='text/plain',
                    headers={'Content-Disposition': f'attachment; filename="ECF_rascunho_{contexto["ano"]}.txt"'})
