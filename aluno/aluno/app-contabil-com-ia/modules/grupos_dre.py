import calendar
import json
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from psycopg2.extras import Json, RealDictCursor

from core.db import connection, fetch
from core.formularios import resposta_edicao
from core.dre_gerencial import calcular, quadro_mensal, agrupar_trimestres, quadro_projetado
from core.modelo_dre import instalar_referencia
from core.estrutura_dre import com_coringa, vinculos_efetivos

grupos_dre = Blueprint('grupos_dre', __name__)
CODIGO = re.compile(r'^[a-z0-9][a-z0-9_.-]{0,63}$')
TIPOS = {'detalhe', 'subtotal'}
PREF_NIVEIS = 'dre-gerencial.hierarquia.v1'


def _opcoes_niveis(contas):
    niveis = sorted({int(c['nivel']) for c in contas if c.get('nivel') and 1 <= int(c['nivel']) <= 20})
    return [{'chave': f'conta:{n}', 'nome': f'Nível {n} da conta'} for n in niveis] + [{'chave': 'centro', 'nome': 'Centro de custo'}]


def _validar_niveis(niveis, opcoes):
    permitidos = {o['chave'] for o in opcoes}
    if not isinstance(niveis, list) or len(niveis) > 21 or any(not isinstance(n, str) or n not in permitidos for n in niveis) or len(set(niveis)) != len(niveis):
        raise ValueError('Selecione níveis existentes, sem repetir, na ordem desejada.')
    return niveis


@grupos_dre.post('/dre-gerencial/niveis')
@login_required
def salvar_niveis():
    try:
        niveis = _validar_niveis(json.loads(request.form.get('niveis', 'null')), _opcoes_niveis(fetch('SELECT nivel FROM contas')))
    except (ValueError, TypeError):
        return resposta_edicao('Selecione níveis existentes, sem repetir, na ordem desejada.', url_for('grupos_dre.demonstracao'), erro=True)
    with connection() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO preferencias_ui(email,chave,valor) VALUES(%s,%s,%s) ON CONFLICT(email,chave) DO UPDATE SET valor=excluded.valor', (current_user.get_id(), PREF_NIVEIS, Json({'niveis': niveis})))
    return resposta_edicao('Níveis do detalhamento atualizados.', url_for('grupos_dre.demonstracao'))


def _grupo_form():
    codigo = request.form.get('codigo', '').strip()
    nome = request.form.get('nome', '').strip()
    tipo = request.form.get('tipo', '').strip()
    try:
        ordem = int(request.form.get('ordem', ''))
    except ValueError:
        raise ValueError('Ordem deve ser um número inteiro.')
    if not CODIGO.fullmatch(codigo):
        raise ValueError('Código: minúsculas, números e sublinhado; comece por letra.')
    if not 1 <= ordem <= 99999 or not 1 <= len(nome) <= 120:
        raise ValueError('Informe nome e ordem válida.')
    if tipo not in TIPOS:
        raise ValueError('Tipo deve ser detalhe ou subtotal.')
    return codigo, nome, ordem, tipo


def _auditar(cur, acao, antes, depois):
    cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)', (acao, Json(antes), Json(depois)))


@grupos_dre.get('/grupos-dre')
@login_required
def cadastro():
    grupos = fetch('SELECT codigo,nome,ordem,tipo FROM dre_grupos ORDER BY ordem,codigo')
    return render_template('grupos_dre.html', title='Estrutura DRE gerencial', active='grupos-dre', grupos=grupos)


@grupos_dre.post('/grupos-dre/referencia')
@login_required
def usar_referencia():
    try:
        with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            resultado = instalar_referencia(cur)
            _auditar(cur, 'DRE gerencial: estrutura de referência aplicada', {}, resultado)
    except ValueError as erro:
        flash(str(erro), 'error')
    else:
        flash(f"Estrutura de referência aplicada: {resultado['grupos_criados']} grupos e {resultado['vinculos_criados']} vínculos.", 'success')
    return redirect(url_for('grupos_dre.cadastro'))


@grupos_dre.post('/grupos-dre/grupo')
@login_required
def criar_grupo():
    try:
        codigo, nome, ordem, tipo = _grupo_form()
    except ValueError as erro:
        return resposta_edicao(str(erro),url_for('grupos_dre.cadastro'),erro=True)
    try:
        with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT 1 FROM dre_grupos WHERE codigo=%s OR ordem=%s', (codigo, ordem))
            if cur.fetchone():
                raise ValueError('Código ou ordem já existe.')
            depois = {'codigo': codigo, 'nome': nome, 'ordem': ordem, 'tipo': tipo}
            cur.execute('INSERT INTO dre_grupos(codigo,nome,ordem,tipo) VALUES(%s,%s,%s,%s)', (codigo, nome, ordem, tipo))
            _auditar(cur, 'DRE gerencial: grupo criado', {}, depois)
    except ValueError as erro:
        return resposta_edicao(str(erro),url_for('grupos_dre.cadastro'),erro=True)
    return resposta_edicao('Grupo criado.',url_for('grupos_dre.cadastro'))


@grupos_dre.post('/grupos-dre/grupo/<codigo>/editar')
@login_required
def editar_grupo(codigo):
    try:
        enviado, nome, ordem, tipo = _grupo_form()
        if enviado != codigo:
            raise ValueError('O código do grupo não pode ser alterado.')
        with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT codigo,nome,ordem,tipo FROM dre_grupos WHERE codigo=%s FOR UPDATE', (codigo,))
            antes = cur.fetchone()
            if not antes:
                abort(404)
            cur.execute('SELECT 1 FROM dre_grupos WHERE ordem=%s AND codigo<>%s', (ordem, codigo))
            if cur.fetchone():
                raise ValueError('Essa ordem já está em uso.')
            if tipo == 'subtotal':
                cur.execute('SELECT 1 FROM dre_vinculos WHERE grupo_codigo=%s UNION ALL SELECT 1 FROM dre_contas_config WHERE grupo_codigo=%s UNION ALL SELECT 1 FROM dre_centros_config WHERE grupo_codigo=%s LIMIT 1', (codigo,codigo,codigo))
                if cur.fetchone():
                    raise ValueError('Remova os vínculos antes de transformar um grupo em subtotal.')
            depois = {'codigo': codigo, 'nome': nome, 'ordem': ordem, 'tipo': tipo}
            cur.execute('UPDATE dre_grupos SET nome=%s,ordem=%s,tipo=%s WHERE codigo=%s', (nome, ordem, tipo, codigo))
            _auditar(cur, 'DRE gerencial: grupo editado', dict(antes), depois)
    except ValueError as erro:
        return resposta_edicao(str(erro),url_for('grupos_dre.cadastro'),erro=True)
    return resposta_edicao('Grupo atualizado.',url_for('grupos_dre.cadastro'))


@grupos_dre.post('/grupos-dre/grupo/<codigo>/excluir')
@login_required
def excluir_grupo(codigo):
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT codigo,nome,ordem,tipo FROM dre_grupos WHERE codigo=%s FOR UPDATE', (codigo,))
        antes = cur.fetchone()
        if not antes:
            abort(404)
        cur.execute('SELECT (SELECT count(*) FROM dre_vinculos WHERE grupo_codigo=%s)+(SELECT count(*) FROM dre_contas_config WHERE grupo_codigo=%s)+(SELECT count(*) FROM dre_centros_config WHERE grupo_codigo=%s) AS count', (codigo,codigo,codigo))
        vinculados = cur.fetchone()['count']
        if vinculados:
            flash('Remova os vínculos deste grupo antes de excluí-lo.', 'error')
            return redirect(url_for('grupos_dre.cadastro'))
        cur.execute('DELETE FROM dre_grupos WHERE codigo=%s', (codigo,))
        _auditar(cur, 'DRE gerencial: grupo excluído', dict(antes), {})
    flash('Grupo removido. Lançamentos foram preservados.', 'success')
    return redirect(url_for('grupos_dre.cadastro'))


@grupos_dre.post('/grupos-dre/vinculo')
@login_required
def vincular():
    conta_id = request.form.get('conta_id', '').strip()
    centro_id = request.form.get('centro_id', '').strip()
    grupo_codigo = request.form.get('grupo_codigo', '').strip()
    try:
        with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT conta_id FROM contas WHERE conta_id=%s AND grupo='resultado' AND analitica=true", (conta_id,))
            conta = cur.fetchone()
            cur.execute("SELECT codigo,tipo FROM dre_grupos WHERE codigo=%s", (grupo_codigo,))
            grupo = cur.fetchone()
            if not conta:
                raise ValueError('Selecione uma conta de resultado existente.')
            cur.execute('SELECT 1 FROM dre_contas_config WHERE conta_id=%s', (conta_id,))
            if cur.fetchone():
                raise ValueError('Defina a linha DRE gerencial no cadastro desta conta.')
            if not grupo or grupo['tipo'] != 'detalhe':
                raise ValueError('Vínculo só pode apontar para grupo do tipo detalhe.')
            if centro_id:
                cur.execute('SELECT 1 FROM centros WHERE centro_id=%s LIMIT 1', (centro_id,))
                if not cur.fetchone():
                    raise ValueError('Centro de custo inexistente.')
            cur.execute('SELECT grupo_codigo FROM dre_vinculos WHERE conta_id=%s AND centro_id=%s FOR UPDATE', (conta_id, centro_id))
            antes = cur.fetchone()
            cur.execute('''INSERT INTO dre_vinculos(conta_id,centro_id,grupo_codigo) VALUES(%s,%s,%s)
                           ON CONFLICT(conta_id,centro_id) DO UPDATE SET grupo_codigo=excluded.grupo_codigo''', (conta_id, centro_id, grupo_codigo))
            _auditar(cur, 'DRE gerencial: vínculo salvo', {'conta_id': conta_id, 'centro_id': centro_id, 'grupo_codigo': antes['grupo_codigo'] if antes else None}, {'conta_id': conta_id, 'centro_id': centro_id, 'grupo_codigo': grupo_codigo})
    except ValueError as erro:
        return resposta_edicao(str(erro),url_for('grupos_dre.cadastro'),erro=True)
    return resposta_edicao('Vínculo salvo.',url_for('grupos_dre.cadastro'))


@grupos_dre.post('/grupos-dre/vinculo/remover')
@login_required
def remover_vinculo():
    conta_id = request.form.get('conta_id', '').strip()
    centro_id = request.form.get('centro_id', '').strip()
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT conta_id,centro_id,grupo_codigo FROM dre_vinculos WHERE conta_id=%s AND centro_id=%s FOR UPDATE', (conta_id, centro_id))
        antes = cur.fetchone()
        if not antes:
            abort(404)
        cur.execute('DELETE FROM dre_vinculos WHERE conta_id=%s AND centro_id=%s', (conta_id, centro_id))
        _auditar(cur, 'DRE gerencial: vínculo removido', dict(antes), {})
    flash('Vínculo removido. Lançamentos foram preservados.', 'success')
    return redirect(url_for('grupos_dre.cadastro'))


@grupos_dre.get('/dre-gerencial')
@login_required
def demonstracao():
    grupos = fetch('SELECT codigo,nome,ordem,tipo FROM dre_grupos ORDER BY ordem,codigo')
    grupos = com_coringa(grupos)
    meses = fetch("SELECT DISTINCT to_char(data,'YYYY-MM') AS competencia FROM lancamentos ORDER BY competencia")
    disponiveis = [x['competencia'] for x in meses]
    if not disponiveis:
        return render_template('sem_base.html', title='DRE gerencial', active='dre-gerencial')
    corte = disponiveis[-1]
    anos = sorted({p[:4] for p in disponiveis} | {p['competencia'][:4] for p in fetch('SELECT DISTINCT competencia FROM orcamento')})
    legado = request.args.get('competencia', '')
    ano_texto = request.args.get('ano') or (legado[:4] if legado else corte[:4])
    if ano_texto not in anos:
        abort(400, description='Ano sem dados disponíveis.')
    ano = int(ano_texto)
    visao = request.args.get('visao', 'mensal')
    if visao not in ('mensal', 'trimestral'):
        abort(400, description='Visão inválida.')
    # O filtro escolhe o ano; o corte vem da carga, não da célula consultada.
    competencia = min(f'{ano}-12', corte) if corte[:4] >= ano_texto else f'{ano}-12'
    mov = fetch('SELECT data,conta_id,centro_id,debito_centavos,credito_centavos,tipo FROM lancamentos WHERE data BETWEEN %s AND %s ORDER BY data,linha_id', (f'{ano-1}-01-01', f'{ano}-12-31'))
    orcamento = fetch('SELECT competencia,conta_id,valor_dc_centavos FROM orcamento WHERE left(competencia,4)=%s ORDER BY competencia,conta_id', (ano_texto,))
    from core.classificacao import classificar
    mov = classificar(mov)
    contas = fetch('SELECT conta_id,descricao,grupo,conta_pai_id,ordem,nivel,analitica FROM contas ORDER BY ordem,conta_id')
    vinculos = vinculos_efetivos(fetch('SELECT conta_id,centro_id,grupo_codigo FROM dre_vinculos'),fetch('SELECT * FROM dre_contas_config'),fetch('SELECT * FROM dre_centros_config'))
    subtotais = [grupo for grupo in grupos if grupo['tipo'] == 'subtotal']
    base_padrao = 'receita_liquida' if any(grupo['codigo'] == 'receita_liquida' for grupo in subtotais) else (subtotais[0]['codigo'] if subtotais else '')
    base_av = request.args['base_av'] if 'base_av' in request.args else base_padrao
    if 'base_av' in request.args and (not base_av or base_av not in {grupo['codigo'] for grupo in subtotais}):
        abort(400, description='Base de AV deve ser um subtotal cadastrado.')
    opcoes_niveis = _opcoes_niveis(contas)
    preferencias = fetch('SELECT valor FROM preferencias_ui WHERE email=%s AND chave=%s', (current_user.get_id(), PREF_NIVEIS))
    niveis = None
    if preferencias:
        salvo = preferencias[0]['valor']
        try:
            niveis = _validar_niveis(salvo.get('niveis'), opcoes_niveis) if isinstance(salvo, dict) else None
        except ValueError:
            niveis = None
    selecionados = niveis if niveis is not None else [o['chave'] for o in opcoes_niveis]
    por_chave = {o['chave']: o for o in opcoes_niveis}
    editor_niveis = [dict(por_chave[k], selecionado=True) for k in selecionados] + [dict(o, selecionado=False) for o in opcoes_niveis if o['chave'] not in selecionados]
    quadro = quadro_projetado(mov, orcamento, contas, grupos, vinculos, ano, corte, base_av=base_av, niveis=niveis, centros=fetch('SELECT centro_id,descricao FROM centros'))
    if visao == 'trimestral':
        quadro = agrupar_trimestres(quadro)
    nomes = {x['conta_id']: x['descricao'] for x in contas}
    for item in quadro['nao_classificadas']:
        item['descricao'] = nomes.get(item['conta_id'], item['conta_id'])
    base_av_nome = next((grupo['nome'] for grupo in subtotais if grupo['codigo'] == base_av), '')
    return render_template('dre_gerencial.html', title='DRE gerencial', active='dre-gerencial', anos=anos, ano=ano_texto, corte=corte, competencia=competencia, visao=visao, quadro=quadro, subtotais=subtotais, base_av=base_av, base_av_nome=base_av_nome, editor_niveis=editor_niveis)
