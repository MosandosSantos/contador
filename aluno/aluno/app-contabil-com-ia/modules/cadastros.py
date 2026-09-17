from flask import Blueprint,request,render_template,redirect,flash,Response
from flask_login import login_required
from psycopg2.extras import Json,RealDictCursor
from core.db import fetch,connection
from core.formularios import resposta_edicao
from core.ecd import gerar_ecd
from core.carga import conta_normalizada,CONTA_CAMPOS
from core.arvore import linearizar,com_ancestrais
from core.estrutura_dre import apresentar_contas,salvar_conta,salvar_centro

cadastros=Blueprint('cadastros',__name__)

@cadastros.get('/exportar/ecd')
@login_required
def exportar_ecd():
    """ECD (SPED Contábil) em RASCUNHO para conferência do contador no PVA."""
    from datetime import date, timedelta
    empresa = fetch('SELECT * FROM empresa WHERE id=1')
    if not empresa:
        flash('Cadastre a empresa (Cadastros → Empresa) antes de exportar o ECD.','error')
        return redirect('/empresa')
    contas = fetch('SELECT conta_id,descricao,grupo,analitica,nivel,natureza,cod_referencial FROM contas ORDER BY ordem,conta_id')
    mov = fetch('SELECT documento_id,data,conta_id,debito_centavos,credito_centavos,historico FROM lancamentos ORDER BY data,documento_id')
    if not mov:
        flash('Importe os lançamentos antes de exportar o ECD.','error')
        return redirect('/importar')
    hoje = date.today()
    # Período padrão: último mês COM lançamentos na base (data máxima).
    dt_fim = max(m['data'] for m in mov)
    if hasattr(dt_fim, 'year'):
        dt_ini = date(dt_fim.year, dt_fim.month, 1)
    else:
        dt_fim = date.fromisoformat(str(dt_fim)[:10])
        dt_ini = date(dt_fim.year, dt_fim.month, 1)
    try:
        texto, avisos = gerar_ecd(dict(empresa[0]), contas, mov, dt_ini.isoformat(), dt_fim.isoformat())
    except ValueError as e:
        flash(str(e), 'error')
        return redirect('/empresa')
    if avisos:
        flash('ECD gerado com avisos: ' + ' · '.join(avisos[:3]) + (' …' if len(avisos) > 3 else ''), 'error')
    else:
        flash('ECD rascunho gerado. Confira no PVA da Receita antes de qualquer uso oficial.', 'success')
    nome = 'ECD_rascunho_' + dt_ini.strftime('%Y%m%d') + '_' + dt_fim.strftime('%Y%m%d') + '.txt'
    # SPED/PVA espera ISO-8859-1 (latin-1), não UTF-8.
    return Response(texto.encode('iso-8859-1', 'replace'), mimetype='text/plain',
                    headers={'Content-Disposition': f'attachment; filename="{nome}"'})
COMPONENTES={'':'Não se aplica','caixa':'Caixa e bancos','clientes':'Clientes / recebíveis','estoques':'Estoques','imobilizado':'Imobilizado','redutora_imobilizado':'Depreciação acumulada','fornecedores':'Fornecedores','remuneracao':'Remunerações a pagar','tributos':'Tributos a pagar','emprestimos':'Empréstimos','capital':'Capital social','lucros_acumulados':'Lucros acumulados','reservas':'Reservas','outros':'Outros'}
LINHAS={'':'Não classificada','receita_bruta':'Receita bruta','deducoes':'Deduções','custos_servicos':'Custos dos serviços','pessoal':'Despesas de pessoal','estrutura':'Despesas de estrutura','depreciacao':'Depreciação','financeiro':'Resultado financeiro','tributos_resultado':'Tributos sobre resultado'}
COMPONENTES.update(receita='Receita',deducoes='Deduções',custos='Custos',pessoal='Pessoal',estrutura='Estrutura',depreciacao='Depreciação',financeiro='Financeiro',tributos_resultado='Tributos sobre resultado')

@cadastros.route('/contas',methods=['GET','POST'])
@login_required
def contas():
    if request.method=='POST':
        try:
            c=conta_normalizada(dict(request.form,nivel=1,analitica=request.form.get('analitica')=='1'))
            if c['componente'] not in COMPONENTES or c['linha_dre'] not in LINHAS:raise ValueError('Classificação inválida.')
            if c['analitica'] and c['grupo']=='pl' and c['componente'] not in ('capital','lucros_acumulados','reservas','outros'):raise ValueError('Informe o componente do patrimônio líquido.')
            with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT pg_advisory_xact_lock(20260911)')
                cur.execute('SELECT * FROM contas');allc={x['conta_id']:dict(x) for x in cur.fetchall()};antes=allc.get(c['conta_id'],{})
                if antes and request.form.get('operacao')=='criar':raise ValueError('Essa conta já existe. Use Editar no registro cadastrado.')
                allc[c['conta_id']]=c;seen={c['conta_id']};pai=c['conta_pai_id']
                def grupo_compativel(pai,filha):return pai==filha or (pai=='passivo' and filha=='pl') or pai=='pendente'
                if any(x['conta_pai_id']==c['conta_id'] and not grupo_compativel(c['grupo'],x['grupo']) for x in allc.values()):raise ValueError('O grupo da conta pai precisa ser compatível com o das filhas.')
                while pai:
                    if pai in seen:raise ValueError('A hierarquia contém um ciclo.')
                    p=allc.get(pai)
                    if not p or p['analitica']:raise ValueError('Escolha uma conta pai sintética existente.')
                    if not grupo_compativel(p['grupo'],c['grupo']):raise ValueError('Pai e filha precisam pertencer a grupos patrimoniais compatíveis.')
                    seen.add(pai);pai=p['conta_pai_id']
                if not c['analitica']:
                    cur.execute('SELECT 1 FROM lancamentos WHERE conta_id=%s LIMIT 1',(c['conta_id'],))
                    if cur.fetchone():raise ValueError('Conta com lançamentos não pode ser sintética.')
                elif any(x['conta_pai_id']==c['conta_id'] for x in allc.values()):raise ValueError('Conta com filhas precisa permanecer sintética.')
                cur.execute('INSERT INTO contas('+','.join(CONTA_CAMPOS)+') VALUES('+','.join(['%s']*len(CONTA_CAMPOS))+') ON CONFLICT(conta_id) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in CONTA_CAMPOS[1:]),tuple(c[k] for k in CONTA_CAMPOS))
                for node in linearizar(list(allc.values())):
                    cur.execute('UPDATE contas SET nivel=%s WHERE conta_id=%s',(node['nivel'],node['conta_id']))
                    if node['conta_id']==c['conta_id']:c['nivel']=node['nivel']
                if 'dre_destino' in request.form:
                    cur.execute('SELECT modo,grupo_codigo FROM dre_contas_config WHERE conta_id=%s',(c['conta_id'],))
                    config_antes=cur.fetchone()
                    cur.execute('SELECT centro_id,grupo_codigo FROM dre_vinculos WHERE conta_id=%s',(c['conta_id'],))
                    antes=dict(antes,dre_config=dict(config_antes) if config_antes else None,dre_vinculos=[dict(v) for v in cur.fetchall()])
                    salvar_conta(cur,c,request.form.get('dre_destino','').strip())
                    c['dre_destino']=request.form.get('dre_destino','').strip()
                if c['grupo']!='resultado':cur.execute('DELETE FROM dre_vinculos WHERE conta_id=%s',(c['conta_id'],))
                elif c['linha_dre'] and 'dre_destino' not in request.form:
                    cur.execute("INSERT INTO dre_vinculos SELECT %s,'',codigo FROM dre_grupos WHERE codigo=%s AND tipo='detalhe' ON CONFLICT DO NOTHING",(c['conta_id'],c['linha_dre']))
                cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Cadastro de conta',Json(antes),Json(c)))
        except (ValueError,TypeError) as e:
            return resposta_edicao(str(e),'/contas',erro=True)
        return resposta_edicao('Conta salva. Os demonstrativos usam a classificação atual.','/contas')
    rows=fetch('SELECT * FROM contas ORDER BY ordem,conta_id')
    rows=apresentar_contas(rows,fetch('SELECT * FROM dre_contas_config'),fetch('SELECT * FROM dre_vinculos'))
    tree=linearizar(rows)
    edit=next((x for x in tree if x['conta_id']==request.args.get('editar')),None)
    filtered=[c['node_id'] for c in tree if (not request.args.get('pendentes') or (c['analitica'] and (c['grupo']=='pendente' or (c['grupo'] in ('ativo','passivo') and c['classe_bp']=='pendente')))) and request.args.get('q','').casefold() in (c['conta_id']+' '+c['descricao']).casefold()]
    selected=com_ancestrais(tree,filtered)
    return render_template('contas.html',title='Plano de contas',active='contas',rows=selected,allcontas=tree,edit=edit or {},componentes=COMPONENTES,linhas=LINHAS,linhas_gerenciais=fetch("SELECT codigo,nome FROM dre_grupos WHERE tipo='detalhe' ORDER BY ordem,codigo"),
                           sinteticas=sum(not c['analitica'] for c in tree),analiticas=sum(c['analitica'] for c in tree),max_nivel=max((c['nivel'] for c in tree),default=0))

@cadastros.route('/centros',methods=['GET','POST'])
@login_required
def centros():
    if request.method=='POST':
        codigo=request.form.get('centro_id','').strip();descricao=request.form.get('descricao','').strip()
        try:
            if not codigo or len(codigo)>100 or not descricao or len(descricao)>300:
                raise ValueError('Informe código e descrição válidos.')
            with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT pg_advisory_xact_lock(20260911)')
                cur.execute('SELECT c.*,d.grupo_codigo FROM centros c LEFT JOIN dre_centros_config d USING(centro_id) WHERE centro_id=%s',(codigo,));antes=cur.fetchone()
                if antes and request.form.get('operacao')=='criar':raise ValueError('Esse centro já existe. Use Editar no registro cadastrado.')
                cur.execute('INSERT INTO centros(centro_id,descricao) VALUES(%s,%s) ON CONFLICT(centro_id) DO UPDATE SET descricao=excluded.descricao',(codigo,descricao))
                depois={'centro_id':codigo,'descricao':descricao}
                if 'dre_destino' in request.form:
                    depois['dre_destino']=request.form.get('dre_destino','').strip()
                    salvar_centro(cur,codigo,depois['dre_destino'])
                cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Cadastro de centro',Json(dict(antes) if antes else {}),Json(depois)))
        except ValueError as e:
            return resposta_edicao(str(e),'/centros',erro=True)
        return resposta_edicao('Centro de custo salvo.','/centros')
    return render_template('centros.html',title='Centros de custo',active='centros',rows=fetch("SELECT c.*,COALESCE(d.grupo_codigo,'') AS dre_destino FROM centros c LEFT JOIN dre_centros_config d USING(centro_id) ORDER BY centro_id"),regras=fetch('SELECT * FROM regras_centros ORDER BY prioridade'),linhas_gerenciais=fetch("SELECT codigo,nome FROM dre_grupos WHERE tipo='detalhe' ORDER BY ordem,codigo"))

@cadastros.post('/centros/regra')
@login_required
def regra_centro():
    from datetime import date
    import json
    try:
        conta=request.form.get('conta_id','').strip();origem=request.form.get('centro_origem','').strip();destino=request.form.get('centro_destino','').strip()
        inicio=date.fromisoformat(request.form.get('inicio',''));fim=date.fromisoformat(request.form.get('fim',''));prioridade=int(request.form.get('prioridade',''))
        motivo=request.form.get('justificativa','').strip()
        if inicio>fim or not 1<=prioridade<=99999 or not motivo or len(motivo)>500 or len(origem)>100 or origem==destino:raise ValueError('Confira vigência, prioridade, centros distintos e justificativa.')
        with connection() as conn,conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(20260911)')
            if conta:
                cur.execute('SELECT 1 FROM contas WHERE conta_id=%s',(conta,))
                if not cur.fetchone():raise ValueError('Conta inexistente.')
            cur.execute('SELECT 1 FROM centros WHERE centro_id=%s',(destino,))
            if not cur.fetchone():raise ValueError('Cadastre o centro de destino antes de criar a regra.')
            cur.execute('SELECT 1 FROM regras_centros WHERE prioridade=%s',(prioridade,))
            if cur.fetchone():raise ValueError('Essa prioridade está em uso. Menor número vence.')
            cur.execute('INSERT INTO regras_centros(conta_id,centro_origem,centro_destino,inicio,fim,prioridade,justificativa) VALUES(%s,%s,%s,%s,%s,%s,%s)',(conta,origem,destino,inicio,fim,prioridade,motivo))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Regra de centro criada',Json({}),Json({'conta_id':conta,'origem':origem,'destino':destino,'inicio':str(inicio),'fim':str(fim),'prioridade':prioridade,'justificativa':motivo})))
    except (ValueError,TypeError) as e:
        return resposta_edicao(str(e),'/centros',erro=True)
    return resposta_edicao('Regra aplicada aos relatórios. O centro original permanece nos lançamentos.','/centros')

def _linhas_referencial(bruto: bytes, nome: str):
    """Lê CSV ou a primeira aba de um XLSX e devolve dicionários das linhas."""
    import csv as _csv
    import io as _io
    if nome.lower().endswith('.csv'):
        for encoding in ('utf-8-sig', 'latin-1'):
            try:
                texto = bruto.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError('Não consegui decodificar o CSV.')
        amostra = texto[:2048]
        separador = ';' if amostra.count(';') > amostra.count(',') else ','
        leitor = _csv.DictReader(_io.StringIO(texto), delimiter=separador)
        return [dict(linha) for linha in leitor if any((v or '').strip() for v in linha.values() if isinstance(v, str))]
    if nome.lower().endswith(('.xlsx', '.xlsm')):
        from openpyxl import load_workbook
        livro = load_workbook(_io.BytesIO(bruto), read_only=True, data_only=True)
        aba = livro[livro.sheetnames[0]]
        linhas = list(aba.iter_rows(values_only=True))
        livro.close()
        if not linhas:
            return []
        cabecalho = [str(c).strip() if c is not None else '' for c in linhas[0]]
        return [dict(zip(cabecalho, linha)) for linha in linhas[1:]
                if any(c is not None and str(c).strip() for c in linha)]
    raise ValueError('Formato não suportado: use CSV ou XLSX.')


@cadastros.post('/contas/referencial')
@login_required
def importar_referencial():
    """Importação em lote de códigos referenciais (bloco 0500 do ECD)."""
    arquivo = request.files.get('arquivo')
    if not arquivo or not arquivo.filename:
        return resposta_edicao('Escolha a planilha com as colunas conta e cod_referencial.', '/contas', erro=True)
    try:
        bruto = arquivo.read()
        if len(bruto) > 12 * 1024 * 1024:
            raise ValueError('Arquivo maior que 12 MB.')
        try:
            linhas = _linhas_referencial(bruto, arquivo.filename)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError('Não consegui ler a planilha: ' + str(e))
        pares = {}
        for ln in linhas:
            conta = str(ln.get('conta_id') or ln.get('conta') or '').strip()
            ref = str(ln.get('cod_referencial') or ln.get('codigo_referencial') or '').strip()
            if conta and ref:
                pares[conta] = ref
        if not pares:
            raise ValueError('Nenhuma linha com conta e cod_referencial foi encontrada.')
        existentes = {c['conta_id']: c for c in fetch('SELECT conta_id,descricao,cod_referencial FROM contas')}
        desconhecidas = [c for c in pares if c not in existentes]
        if desconhecidas:
            raise ValueError('Contas inexistentes no plano: ' + ', '.join(sorted(desconhecidas)[:5]) + (' …' if len(desconhecidas) > 5 else ''))
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(20260911)')
            atualizados = 0
            for conta, ref in sorted(pares.items()):
                if existentes[conta].get('cod_referencial') == ref:
                    continue
                cur.execute('UPDATE contas SET cod_referencial=%s WHERE conta_id=%s', (ref, conta))
                cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                            ('Referencial 0500 importado', Json({'conta_id': conta, 'cod_referencial': existentes[conta].get('cod_referencial')}),
                             Json({'conta_id': conta, 'cod_referencial': ref})))
                atualizados += 1
        if atualizados:
            flash(f'{atualizados} código(s) referencial(is) atualizados. Eles entram no bloco 0500 do ECD rascunho.', 'success')
            return resposta_edicao(f'{atualizados} código(s) referencial(is) atualizados. Eles entram no bloco 0500 do ECD rascunho.', '/contas')
        flash('Nada a alterar: os códigos enviados já estavam gravados.', 'success')
        return resposta_edicao('Nada a alterar: os códigos enviados já estavam gravados.', '/contas')
    except (ValueError, TypeError) as e:
        return resposta_edicao(str(e), '/contas', erro=True)


@cadastros.post('/centros/regra/<int:regra>/remover')
@login_required
def remover_regra(regra):
    import json
    with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT * FROM regras_centros WHERE id=%s FOR UPDATE',(regra,));old=cur.fetchone()
        if old:
            cur.execute('DELETE FROM regras_centros WHERE id=%s',(regra,))
            cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Regra de centro removida',Json(json.loads(json.dumps(dict(old),default=str))),Json({})))
    flash('Regra removida. Os relatórios voltam a usar a classificação correspondente.','success')
    return redirect('/centros')
