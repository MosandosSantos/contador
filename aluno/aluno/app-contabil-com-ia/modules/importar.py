import secrets
from flask import Blueprint,request,render_template,redirect,url_for,flash,session,abort,Response
from flask_login import login_required,current_user
from psycopg2.extras import Json
from core.db import fetch,connection
from core.planilha import ler_planilha
from core.carga import conferir,gravar

importacao=Blueprint('importacao',__name__)

def mostrar(payload=None,token=None):
    from core.arvore import linearizar
    stats=fetch("SELECT count(*) AS linhas,min(data) AS inicio,max(data) AS fim FROM lancamentos")[0]
    pendentes=fetch("SELECT count(*) AS n FROM contas WHERE analitica AND (grupo='pendente' OR (grupo IN ('ativo','passivo') AND classe_bp='pendente'))")[0]['n']
    contas_previa=linearizar(payload.get('contas',[])) if payload else []
    return render_template('importar.html',title='Importar lançamentos',active='importar',stats=stats,pendentes=pendentes,payload=payload,token=token,contas_previa=contas_previa)

@importacao.route('/importar',methods=['GET','POST'])
@login_required
def inicio():
    if request.method=='GET':return mostrar()
    f=request.files.get('file')
    if not f or not f.filename:flash('Selecione uma planilha XLSX ou CSV.','error');return mostrar(),400
    try:
        payload=ler_planilha(f.read(),f.filename)
        catalogo=conferir(payload,fetch('SELECT * FROM contas'))
        from core.dre_importacao import validar_dre
        validar_dre(payload.get('dre'),fetch('SELECT * FROM dre_grupos'))
        if payload.get('dre'):
            try:validar_dre(payload['dre'],fetch('SELECT * FROM dre_grupos'),'acrescentar')
            except ValueError as erro:payload['dre_aviso_acrescentar']=str(erro)
        payload['resumo']={'linhas':len(payload['rows']),'contas':len({x['conta_id'] for x in payload['rows']}),'inicio':min(x['data'] for x in payload['rows']),'fim':max(x['data'] for x in payload['rows']),'debitos':sum(x['debito_centavos'] for x in payload['rows']),'creditos':sum(x['credito_centavos'] for x in payload['rows'])}
        if payload.get('orcamento') is not None:
            payload['resumo']['orcamento'] = len(payload['orcamento'])
        payload['pendentes']=[c['conta_id'] for c in catalogo if c['analitica'] and c['grupo']=='pendente']
        token=secrets.token_urlsafe(32)
        with connection() as conn,conn.cursor() as cur:
            cur.execute("DELETE FROM importacoes_previa WHERE criada<now()-interval '2 hours'")
            cur.execute('INSERT INTO importacoes_previa(token,arquivo,conteudo) VALUES(%s,%s,%s)',(token,f.filename[:200],Json(payload)))
        session['importacao_token']=token
        return mostrar(payload,token)
    except ValueError as e:flash(str(e),'error');return mostrar(),400

@importacao.post('/importar/confirmar')
@login_required
def confirmar():
    token=request.form.get('token','')
    if not token or not secrets.compare_digest(token,session.get('importacao_token','')):abort(400,description='Prévia expirada; envie o arquivo novamente.')
    found=fetch("SELECT conteudo,arquivo FROM importacoes_previa WHERE token=%s AND criada>now()-interval '2 hours'",(token,))
    if not found:abort(400,description='Prévia expirada.')
    try:n,i=gravar(found[0]['conteudo'],request.form.get('modo',''),arquivo=found[0]['arquivo'],usuario=current_user.get_id())
    except ValueError as e:flash(str(e),'error');return mostrar(found[0]['conteudo'],token),400
    with connection() as conn,conn.cursor() as cur:cur.execute('DELETE FROM importacoes_previa WHERE token=%s',(token,))
    session.pop('importacao_token',None)
    flash(f'Importação concluída: {n} linhas novas; {i} já existentes. Confira a classificação das contas.','success')
    return redirect('/contas')

@importacao.get('/historico')
@login_required
def historico():
    rows=fetch("SELECT id,data AT TIME ZONE 'America/Sao_Paulo' AS momento,antes,depois FROM auditoria WHERE acao=%s ORDER BY data DESC,id DESC",('Importação',))
    for row in rows:
        row['depois']=row['depois'] or {}
    return render_template('historico_importacoes.html',title='Histórico de importações',active='historico',rows=rows,
                           modos={'acrescentar':'Acrescentar','substituir':'Nova base'})

@importacao.get('/modelo/planilha.xlsx')
@importacao.get('/modelo/protheus.xlsx')
@login_required
def modelo():
    from core.modelo_planilha import gerar_modelo, gerar_modelo_protheus
    from pathlib import Path
    import json
    root=Path(__file__).resolve().parents[1]
    # Modelo somente sintético: nunca incorpora dados carregados pelo usuário.
    pasta_dados=root/'dados/hierarquia_cinco_niveis'
    contas=json.loads((pasta_dados/'contas.json').read_text(encoding='utf-8'))
    for c in contas:
        c.setdefault('classe_bp','nao_circulante' if c.get('componente') in ('imobilizado','redutora_imobilizado') else (c['grupo'] if c['grupo'] in ('pl','resultado') else 'circulante'))
    mov=json.loads((pasta_dados/'lancamentos.json').read_text(encoding='utf-8'))
    protheus=request.path.endswith('/protheus.xlsx')
    dre=json.loads((pasta_dados/'dre_gerencial.json').read_text(encoding='utf-8'))
    arquivo_orcamento=pasta_dados/'orcamento.json'
    orcamento=json.loads(arquivo_orcamento.read_text(encoding='utf-8')) if arquivo_orcamento.exists() else None
    conteudo=gerar_modelo_protheus(contas,mov,dre=dre,orcamento=orcamento) if protheus else gerar_modelo(contas,mov,dre=dre,orcamento=orcamento)
    nome='Modelo_Protheus.xlsx' if protheus else 'Modelo_Lancamentos.xlsx'
    return Response(conteudo,mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="{nome}"'})
