import csv
import io
import json
import re
from pathlib import Path
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from flask import Blueprint,request,render_template,redirect,url_for,flash,Response,abort,jsonify
from flask_login import login_required,current_user
from psycopg2.extras import Json,RealDictCursor
from core.db import fetch,connection
from core.formularios import resposta_edicao
from core.calculos import demonstrativo,comparar,conciliar,limites,COMPONENTES
from core.importacao import ler_csv,importar,validar_extrato

pages=Blueprint('pages',__name__)
ROOT=Path(__file__).resolve().parents[1]
NAV=[{'slug':s,'title':t,'icon':i} for s,t,i in [
 ('importar','Importar','ph-upload-simple'),('contas','Plano de contas','ph-tree-structure'),('centros','Centros de custo','ph-buildings'),('grupos-dre','Estrutura DRE gerencial','ph-sliders-horizontal'),('home','Visão geral','ph-chart-pie-slice'),('conciliacao','Conciliação','ph-arrows-left-right'),('balancete','Balancete','ph-table'),('balanco','Balanço patrimonial','ph-scales'),('razao','Razão contábil','ph-list-bullets'),('dre','DRE de referência','ph-chart-bar'),('dre-gerencial','DRE gerencial','ph-chart-line'),('dmpl','DMPL','ph-columns'),('dfc-direto','Fluxo de caixa direto','ph-wallet'),('dfc-indireto','Fluxo de caixa indireto','ph-arrows-left-right'),('dfc','Fluxo de caixa','ph-wallet'), ('orcamento','Orçado × Realizado','ph-calendar'),('analise','Análise financeira','ph-chart-line-up'), ('empresa','Empresa','ph-buildings'),('participantes','Participantes','ph-users-three'),('usuarios','Usuários','ph-user-circle'),('ecf','ECF fiscal','ph-file-text'), ('nf','NF e operações','ph-receipt'),('efd-contribuicoes','EFD Contribuições','ph-percent'), ('efd-icms-ipi','EFD ICMS/IPI','ph-tag'),('esocial','eSocial','ph-users-four')]]
LABELS={'receita_bruta':'Receita bruta','deducoes':'Deduções informadas','custos_servicos':'Serviços de terceiros','pessoal':'Pessoal','estrutura':'Estrutura','depreciacao':'Depreciação','financeiro':'Despesas bancárias','tributos_resultado':'Tributos sobre resultado informados','capital':'Capital','lucros_acumulados':'Lucros acumulados','reservas':'Reservas','resultado_corrente':'Resultado corrente','resultado_periodo':'Resultado do período','encerramento':'Encerramento do resultado','distribuicao':'Distribuição de lucros','aporte':'Aporte de capital','reserva':'Transferência para reserva','operacional':'Atividades operacionais','investimento':'Atividades de investimento','financiamento':'Atividades de financiamento'}
# Ordem da demonstração do workshop. /home é o ponto de partida (decisão039).
next(x for x in NAV if x['slug']=='home').update(title='Início',icon='ph-house')
NAV.append({'slug': 'conciliacao-arquivos', 'title': 'Enviar relatórios', 'icon': 'ph-upload-simple'})
NAV.append({'slug': 'historico', 'title': 'Histórico', 'icon': 'ph-clock-counter-clockwise'})
NAV.append({'slug': 'minha-senha', 'title': 'Minha senha', 'icon': 'ph-lock-key'})
MENU_GRUPOS = [
    {'nome': nome, 'slug': slug, 'itens': [next(x for x in NAV if x['slug'] == item) for item in itens]}
    for nome, slug, itens in [
        ('Conciliar', 'conciliar', ['conciliacao-arquivos', 'conciliacao']),
        ('Importar', 'importar', ['importar', 'historico']),
        ('Cadastros', 'cadastros', ['contas', 'centros', 'grupos-dre', 'empresa', 'participantes']),
        ('Relatórios', 'relatorios', ['balancete', 'balanco', 'razao', 'dre', 'dre-gerencial', 'dmpl', 'dfc-direto', 'dfc-indireto', 'analise']),
        ('Orçamento', 'orcamento', ['orcamento']),
        ('Fiscal', 'fiscal', ['ecf', 'nf', 'efd-contribuicoes', 'efd-icms-ipi', 'esocial']),
    ]
]
def label(k):return LABELS.get(k,k.replace('_',' ').capitalize())
LABELS.update(receita_liquida='Receita líquida',resultado='Resultado',variacao_clientes='Variação de clientes',variacao_remuneracao_pagar='Variação de remuneração a pagar',variacao_tributos_pagar='Variação de tributos a pagar')
def cols(*items):return [{'key':k,'label':t,'numeric':n} for k,t,n in items]
def source():
    mov=fetch('SELECT * FROM lancamentos ORDER BY data,documento_id,linha_id')
    for x in mov:x['data']=x['data'].isoformat()
    from core.classificacao import classificar
    mov=classificar(mov)
    return mov,fetch('SELECT * FROM contas ORDER BY conta_id'),fetch('SELECT * FROM orcamento ORDER BY competencia,conta_id')
def money(v):
    if v is None:return 'Sem realizado'
    n=abs(int(v));s=f'{n//100:,}'.replace(',','.')+f',{n%100:02}'
    return ('− ' if v<0 else '')+'R$ '+s
def queryurl(**changes):
    args=request.args.to_dict();args.update(changes)
    return request.path+'?'+urlencode({k:v for k,v in args.items() if v is not None})

def audit_text(v):
    if isinstance(v,list):return '; '.join(x['competencia']+': '+money(x['valor_dc_centavos']) for x in v)
    if 'mensal_centavos' in v:return f"{v['inicio']} a {v['fim']}: {money(v['mensal_centavos'])}/mês"
    if 'destino' in v:return v.get('competencia','')+': '+label(v['destino'])
    if 'linhas' in v:return str(v['linhas'])+' linhas'+(f"; {v['novas']} novas, {v['ignoradas']} já existentes" if 'novas' in v else '')
    return str(v)


def contexto_balancete(mov, contas):
    from core.balancete import construir, opcoes_niveis, validar_niveis
    comp = request.args.get('competencia') or max(x['data'] for x in mov)[:7]
    de_padrao, ate_padrao = limites(comp, request.args.get('alcance','mensal'))
    data_de = request.args.get('data_de',de_padrao)
    data_ate = request.args.get('data_ate',ate_padrao)
    tipo = request.args.get('tipo','mensal')
    opcoes = opcoes_niveis(contas)
    pref = fetch('SELECT valor FROM preferencias_ui WHERE email=%s AND chave=%s',(current_user.get_id(),'balancete.hierarquia.v1'))
    niveis = None
    if pref:
        try:
            niveis = validar_niveis(pref[0]['valor'].get('niveis'),contas)
        except (ValueError,AttributeError):
            pass
    quadro = construir(mov,contas,data_de,data_ate,tipo,niveis,fetch('SELECT * FROM centros'))
    selecionados = quadro['niveis']
    por_chave = {o['chave']:o for o in opcoes}
    editor = [dict(por_chave[k],selecionado=True) for k in selecionados] + [dict(o,selecionado=False) for o in opcoes if o['chave'] not in selecionados]
    from core.balancete import fins_de_mes
    fim_rastreio = fins_de_mes(data_de,data_ate)[-1] if tipo=='mes-a-mes' else data_ate
    for linha in quadro['linhas']:
        conta_id = linha.get('conta_id') or linha.get('conta_no_id')
        args = {'competencia':fim_rastreio[:7],'data_de':data_de[:7]+'-01' if tipo=='mes-a-mes' else data_de,'data_ate':fim_rastreio}
        if conta_id: args['conta'] = conta_id
        if 'centro_id' in linha: args['centro'] = linha['centro_id']
        linha['_url'] = '/razao?'+urlencode(args) if conta_id or 'centro_id' in linha else None
    return dict(active='balancete',title='Balancete',competencia=comp,alcance='mensal',tipo=tipo,data_de=data_de,data_ate=data_ate,balancete=quadro,editor_niveis=editor,rows=[{'conta_id':c.get('conta_no_id',''),'descricao':c['nome'],**c['valores']} for c in quadro['linhas']],columns=[],kpis=[],cards=[],audit=[])


def context(active):
    mov,contas,orc=source()
    if active == 'balancete':
        return contexto_balancete(mov, contas)
    if active in ('balanco','razao','dre','dmpl','dfc-direto','dfc-indireto','orcamento'):
        from modules.relatorios import contexto_relatorio
        return contexto_relatorio(active,mov,contas,orc)
    comp=request.args.get('competencia') or (max(x['data'] for x in mov)[:7] if mov else '2026-01');alcance=request.args.get('alcance','mensal')
    limites(comp,alcance)
    if active not in ('importar','razao','balancete','conciliacao') and any(c['analitica'] and c['grupo']=='pendente' for c in contas):
        raise ValueError('Existem contas sem grupo patrimonial. Abra Plano de contas e conclua a classificação antes de gerar os demonstrativos.')
    rc={(x['competencia'],x['conta_id']):x['destino'] for x in fetch('SELECT * FROM reclassificacoes')}
    r=demonstrativo(mov,contas,comp,alcance,rc)
    if active == 'razao' and ('data_de' in request.args or 'data_ate' in request.args):
        from core.balancete import intervalo
        r['inicio'], r['fim'] = intervalo(request.args.get('data_de'), request.args.get('data_ate'))
    d={'active':active,'title':next(x['title'] for x in NAV if x['slug']==active),'competencia':comp,'alcance':alcance,'intro':'Relatórios calculados a partir da base importada.','rows':[],'columns':[],'kpis':[],'cards':[],'chart':[],'audit':[],'contas':contas,'quadro':None}
    link=lambda a:'/razao?'+urlencode({'competencia':comp,'alcance':alcance,'conta':a})
    if active=='home':
        b=r['balanco'];df=r['dfc'];dr=r['dre']
        d['kpis']=[{'label':'Resultado do período','value':dr['resultado_centavos'],'hint':f'{comp} · {alcance}'},{'label':'Saldo de caixa','value':df['caixa_final_centavos'],'hint':'Saldo no encerramento da competência'},{'label':'Patrimônio líquido','value':b['pl_centavos'],'hint':'Capital + lucros + reservas + resultado'},{'label':'Geração de caixa','value':df['caixa_final_centavos']-df['caixa_inicial_centavos'],'hint':'Variação no período selecionado'}]
        d['cards']=[{'title':'Do saldo ao documento','text':'Abra uma conta no balancete ou no Balanço para conferir seus lançamentos no Razão.'},{'title':'Resultado não é caixa','parts':['Resultado: ',dr['resultado_centavos'],'. Caixa gerado: ',df['caixa_final_centavos']-df['caixa_inicial_centavos'],'. A DFC explica a diferença.']},{'title':'Balanço conferido','parts':['Ativo ',b['ativo_centavos'],' = passivo ',b['passivo_centavos'],' + PL ',b['pl_centavos'],'.']}]
        d['chart']=[{'label':label(k),'value':v} for k,v in df['atividades_centavos'].items()]
    elif active=='balanco':
        d['columns']=cols(('conta','Conta',False),('descricao','Descrição',False),('grupo','Grupo',False),('saldo','Saldo',True))
        for c in contas:
            if c['grupo']=='resultado' or not c['analitica']:continue
            s=r['balanco']['saldos_dc_por_conta'].get(c['conta_id'],0)
            d['rows'].append({'conta':c['conta_id'],'descricao':c['descricao'],'grupo':{'ativo':'Ativo','passivo':'Passivo','pl':'Patrimônio líquido'}[c['grupo']],'saldo':s if c['grupo']=='ativo' else -s,'_url':link(c['conta_id'])})
        d['rows'].append({'conta':'Resultado','descricao':'Resultado ainda não encerrado','grupo':'Patrimônio líquido','saldo':r['balanco']['componentes_pl']['resultado_corrente']})
        for k in ('ativo','passivo','pl'):d['rows'].append({'conta':'TOTAL','descricao':{'ativo':'Ativo','passivo':'Passivo','pl':'Patrimônio líquido'}[k],'grupo':'Total','saldo':r['balanco'][k+'_centavos']})
    elif active=='razao':
        a=request.args.get('conta','');doc=request.args.get('documento','')
        centro=request.args.get('centro')
        descr={c['conta_id']:c['descricao'] for c in contas}
        d['columns']=cols(('data','Data',False),('documento_id','Documento',False),('conta_id','Conta',False),('historico','Histórico',False),('centro_id','Centro',False),('debito_centavos','Débito',True),('credito_centavos','Crédito',True))
        from core.arvore import descendentes
        escopo=descendentes(contas,a) if a else set()
        d['rows']=[dict(x,_url='/razao?'+urlencode({'competencia':comp,'alcance':alcance,'documento':x['documento_id']})) for x in mov if r['inicio']<=x['data']<=r['fim'] and (not a or x['conta_id'] in escopo) and (not doc or x['documento_id']==doc) and (centro is None or x['centro_id']==centro)]
        if 'data_de' in request.args:
            for linha in d['rows']:
                linha['_url'] += '&' + urlencode({'data_de':r['inicio'],'data_ate':r['fim']})
            d['intro'] = 'Lançamentos de ' + r['inicio'][8:10]+'/'+r['inicio'][5:7]+'/'+r['inicio'][:4] + ' a ' + r['fim'][8:10]+'/'+r['fim'][5:7]+'/'+r['fim'][:4]+'.'
        d['intro']+= ' '+(descr.get(a,a) if a else 'Todas as contas.')+(' Documento '+doc if doc else '')
        if a:
            saldo=sum(x['debito_centavos']-x['credito_centavos'] for x in mov if x['conta_id'] in escopo and x['data']<r['inicio'] and (centro is None or x['centro_id']==centro))
            inicio_saldo=saldo
            for x in d['rows']:
                saldo+=x['debito_centavos']-x['credito_centavos'];x['saldo']=saldo
            d['columns']+=cols(('saldo','Saldo D–C',True))
            d['kpis']=[{'label':'Saldo inicial','value':inicio_saldo},{'label':'Débitos','value':sum(x['debito_centavos'] for x in d['rows'])},{'label':'Créditos','value':sum(x['credito_centavos'] for x in d['rows'])},{'label':'Saldo final','value':saldo}]
        if any(x.get('regra_centro_id') for x in d['rows']):d['columns']+=cols(('centro_original','Centro original',False),('regra_centro_id','Regra aplicada',False))
    elif active=='dre':
        d['columns']=cols(('linha','Linha',False),('referencia','DRE de referência',True),('gerencial','DRE gerencial',True))
        for k in ['receita_bruta','deducoes','receita_liquida','custos_servicos','pessoal','estrutura','depreciacao','financeiro','tributos_resultado','resultado']:
            if k=='receita_liquida':v=r['dre']['receita_liquida_centavos'];g=v
            elif k=='resultado':v=r['dre']['resultado_centavos'];g=sum(r['gerencial'].values())
            else:v=r['dre']['linhas_centavos'].get(k,0);g=r['gerencial'].get(k,0)
            row={'linha':label(k),'referencia':v,'gerencial':g}
            account=next((c['conta_id'] for c in contas if c['linha_dre']==k),None)
            if account:row['_url']=link(account)
            d['rows'].append(row)
        d['intro']+=' A reclassificação muda somente a apresentação gerencial da conta 5.2. O resultado total é preservado.'
    elif active=='dmpl':
        d['columns']=cols(('evento','Evento',False),*[(k,label(k),True) for k in COMPONENTES],('total','Total',True))
        for nome,v in [('Saldo inicial',r['dmpl']['inicio'])]+[(label(k),v) for k,v in r['dmpl']['movimentos'].items()]+[('Saldo final',r['dmpl']['fim'])]:
            d['rows'].append({'evento':nome,**v,'total':sum(v.values())})
    elif active=='dfc':
        d['columns']=cols(('linha','Fluxo de caixa',False),('valor','Valor',True))
        df=r['dfc']
        d['rows']=[{'linha':'Caixa inicial','valor':df['caixa_inicial_centavos']}]+[{'linha':label(k),'valor':v} for k,v in df['atividades_centavos'].items()]+[{'linha':'Caixa final','valor':df['caixa_final_centavos']}]
        d['cards']=[{'title':'Método indireto: reconciliação do operacional','text':' + '.join(f'{label(k.removesuffix("_centavos"))}: {money(v)}' for k,v in df['ponte_indireta'].items())+f" = {money(df['operacional_indireto_centavos'])}."}]
    elif active=='orcamento':
        d['premissas']=fetch('SELECT o.competencia,o.conta_id,o.valor_dc_centavos,c.descricao FROM orcamento o JOIN contas c USING(conta_id) WHERE left(o.competencia,4)=%s ORDER BY o.competencia,c.ordem,o.conta_id',(comp[:4],))
        for item in d['premissas']:item['valor_reais']=format(Decimal(item['valor_dc_centavos'])/100,'.2f')
        d['columns']=cols(('competencia','Competência',False),('realizado','Realizado',True),('orcado','Orçamento atual',True),('forecast','Forecast',True),('origem','Origem do forecast',False),('variacao','Realizado menos orçado',True),('anterior','Realizado 2025',True))
        d['rows']=comparar(mov,contas,orc,int(comp[:4]))
        d['columns'][-1]['label']='Realizado '+str(int(comp[:4])-1)
        d['cards']=[{'title':'Resultado projetado nos meses disponíveis','parts':[sum(x['forecast'] or 0 for x in d['rows']),' · realizado nos meses com dados; orçamento nos demais. Sem dado permanece ausente.']}]
        d['intro']+=' Cadastre orçamento por conta e competência. Não altera os lançamentos realizados.'
    elif active=='conciliacao':
        caixa={c['conta_id'] for c in contas if c.get('componente')=='caixa'}
        encontrado=fetch('SELECT extrato FROM conciliacao WHERE id=1');extrato=encontrado[0]['extrato'] if encontrado else []
        inicio_extrato=min((x['data'] for x in extrato),default=r['inicio']);fim_extrato=max((x['data'] for x in extrato),default=r['fim'])
        chave=request.args.get('referencia','documento_id')
        if chave not in ('documento_id','origem_id'):raise ValueError('Referência de conciliação inválida.')
        interno=[{'referencia':x[chave],'valor_centavos':x['debito_centavos']-x['credito_centavos'],'documento_id':x['documento_id']} for x in mov if x['conta_id'] in caixa and x['tipo']!='abertura' and inicio_extrato<=x['data']<=fim_extrato]
        d['columns']=cols(('referencia','Referência',False),('interno','Sistema',True),('extrato','Extrato',True),('diferenca','Diferença',True),('status','Situação',False),('quantidade_extrato','Linhas no extrato',False))
        d['rows']=conciliar(interno,extrato)
        for x in d['rows']:
            if x['documento']:x['_url']='/razao?'+urlencode({'competencia':fim_extrato[:7],'alcance':'acumulado','documento':x['documento']})
        d['intro']='Conciliação no intervalo do extrato: '+inicio_extrato+' a '+fim_extrato+'. Referência externa: '+('documento do lançamento' if chave=='documento_id' else 'identificador de origem')+'. Referências repetidas são exceções, não somas automáticas.'
        if not extrato:d['intro']='Envie o extrato para comparar os recebimentos e pagamentos com os lançamentos importados.'
    elif active=='analise':
        dr=r['dre'];df=r['dfc'];b=r['balanco']
        revenue=dr['receita_liquida_centavos'];profit=dr['resultado_centavos'];cash=df['caixa_final_centavos']-df['caixa_inicial_centavos']
        margin=f'{profit/revenue*100:.1f}%' if revenue else 'indisponível'
        d['cards']=[{'title':'Margem do período','parts':['Receita líquida de ',revenue,', resultado de ',profit,f' e margem de {margin}. Tributos são premissas informadas.']},{'title':'Resultado e caixa','parts':['O caixa variou ',cash,'. Diferença em relação ao resultado: ',cash-profit,'. Consulte a ponte do método indireto na DFC.']},{'title':'Estrutura patrimonial','parts':['O patrimônio líquido financia ',b['pl_centavos'],' de um ativo de ',b['ativo_centavos'],'. Abra o Balanço para conferir as contas.']}]
        d['intro']='Leitura financeira calculada, sem modelo de IA conectado. Os números vêm dos lançamentos do período e podem ser conferidos nos demonstrativos.'
    elif active=='importar':
        d['cards']=[{'title':'Importação que confere antes de gravar','text':'CSV UTF-8 separado por vírgula, valores inteiros em centavos. O documento precisa fechar em zero. Reenviar o mesmo arquivo não duplica linhas.'}]
    if active in ('orcamento','dre','conciliacao','importar'):
        acao={'orcamento':'Premissa: serviços de terceiros','dre':'Reclassificação gerencial','conciliacao':'Extrato importado','importar':'Importação'}[active]
        d['audit']=fetch("SELECT to_char(data AT TIME ZONE 'America/Sao_Paulo','DD/MM/YYYY HH24:MI') AS data,acao,antes,depois FROM auditoria WHERE acao=%s ORDER BY id DESC LIMIT 12",(acao,))
        for item in d['audit']:
            item['antes']=audit_text(item['antes']);item['depois']=audit_text(item['depois'])
    if active in ('balanco','dre','dfc','dmpl'):
        from core.quadros import construir
        d['quadro']=construir(mov,contas,comp,alcance)
        d['columns']=[];d['rows']=[]
        if active=='balanco':
            b=r['balanco'];d['kpis']=[{'label':'Ativo','value':b['ativo_centavos']},{'label':'Passivo','value':b['passivo_centavos']},{'label':'Patrimônio líquido','value':b['pl_centavos']},{'label':'Diferença de fechamento','value':b['ativo_centavos']-b['passivo_centavos']-b['pl_centavos']}]
        elif active=='dre':
            dr=r['dre'];d['intro']='DRE de referência por mês, com subtotais e comparação acumulada. A DRE gerencial possui estrutura própria no cadastro de grupos.'
            d['kpis']=[{'label':'Receita bruta do recorte','value':dr['linhas_centavos'].get('receita_bruta',0)},{'label':'Receita líquida do recorte','value':dr['receita_liquida_centavos']},{'label':'Resultado do recorte','value':dr['resultado_centavos']}]
        elif active=='dfc':
            df=r['dfc'];d['kpis']=[{'label':'Caixa inicial do recorte','value':df['caixa_inicial_centavos']},{'label':'Operacional','value':df['atividades_centavos'].get('operacional',0)},{'label':'Variação de caixa','value':df['caixa_final_centavos']-df['caixa_inicial_centavos']},{'label':'Caixa final do recorte','value':df['caixa_final_centavos']}]
            d['cards']=[];d['intro']='Fluxo direto por atividade e rubrica, derivado das contas marcadas como caixa. Movimentos sem atividade permanecem visíveis para classificação.'
    return d

def display(active):
    if not fetch('SELECT 1 FROM lancamentos LIMIT 1') and active != 'conciliacao':
        return render_template('sem_base.html', title=next(x['title'] for x in NAV if x['slug']==active), active=active)
    if active not in ('razao', 'balancete', 'conciliacao') and fetch("SELECT 1 FROM contas WHERE analitica AND grupo='pendente' LIMIT 1"):
        return render_template('sem_base.html', title=next(x['title'] for x in NAV if x['slug']==active), active=active, classificacao_pendente=True)
    try:d=context(active)
    except ValueError as e:abort(400,description=str(e))
    if active=='balancete':
        return render_template('balancete_arvore.html',**d)
    if d.get('template_relatorio'):
        return render_template(d.pop('template_relatorio'),**d)
    q=request.args.get('q','').casefold()
    if q:d['rows']=[x for x in d['rows'] if q in ' '.join(str(v) for k,v in x.items() if not k.startswith('_')).casefold()]
    for column in d['columns']:
        key=column['key'];term=request.args.get('cf_'+key,'').strip().casefold()
        if term:
            def as_text(row):
                value=row.get(key)
                if value is None:return ''
                if column['numeric']:return money(value)
                if key=='data' and isinstance(value,str) and len(value)>=10:return value[8:10]+'/'+value[5:7]+'/'+value[:4]
                return str(value)
            d['rows']=[row for row in d['rows'] if term in as_text(row).casefold()]
    sort=request.args.get('sort','');order=request.args.get('order','asc')
    if sort in {x['key'] for x in d['columns']}:
        d['rows'].sort(key=lambda x:(x.get(sort) is None,x.get(sort) if x.get(sort) is not None else 0),reverse=order=='desc')
    total=len(d['rows'])
    try:n=int(request.args.get('per_page',100))
    except ValueError:abort(400,description='Quantidade por página inválida.')
    if n not in (10,50,100,500):abort(400,description='Escolha 10, 50, 100 ou 500 linhas por página.')
    try:page=max(1,int(request.args.get('page',1)))
    except ValueError:abort(400,description='Página inválida.')
    maxpage=max(1,(total+n-1)//n);page=min(page,maxpage)
    d.update(total=total,page=page,pages=maxpage,queryurl=queryurl,per_page=n)
    d['rows']=d['rows'][(page-1)*n:page*n]
    return render_template('page.html',**d)

@pages.get('/')
@login_required
def home():return redirect('/home')

@pages.route('/<active>',methods=['GET','POST'])
@login_required
def screen(active):
    if active not in {x['slug'] for x in NAV}:abort(404)
    if active=='home' and request.method=='GET':
        from modules.inicio import contexto
        return render_template('home.html',**contexto())
    if active == 'analise' and request.method == 'GET':
        from modules.analise_financeira import contexto
        return render_template('analise_chat.html', **contexto())
    if active=='dfc' and request.method=='GET':return redirect('/dfc-direto'+('?' + request.query_string.decode() if request.query_string else ''))
    if request.method=='POST':
        try:
            if active=='balancete' or (active=='orcamento' and 'niveis' in request.form):
                from core.balancete import validar_niveis
                niveis=validar_niveis(json.loads(request.form.get('niveis','null')),fetch('SELECT * FROM contas'))
                with connection() as conn, conn.cursor() as cur:
                    cur.execute('INSERT INTO preferencias_ui(email,chave,valor) VALUES(%s,%s,%s) ON CONFLICT(email,chave) DO UPDATE SET valor=excluded.valor',(current_user.get_id(),active+'.hierarquia.v1',Json({'niveis':niveis})))
                return resposta_edicao('Níveis do relatório atualizados.','/'+active)
            if active=='orcamento':
                update_budget()
                return resposta_edicao('Premissa salva. O forecast foi recalculado.','/orcamento')
            elif active=='conciliacao':return redirect('/conciliacao-arquivos', code=303)
            elif active=='importar':upload_journal()
            else:abort(405)
        except (ValueError,InvalidOperation) as e:
            if active in ('orcamento','balancete') and request.headers.get('X-Record-Modal')=='1':
                return resposta_edicao(str(e) if not isinstance(e,InvalidOperation) else 'Informe um valor mensal válido.','/'+active,erro=True)
            flash(str(e),'error');return display(active),400
        return redirect(url_for('pages.screen',active=active))
    return display(active)

def update_budget():
    inicio=request.form.get('inicio','');fim=request.form.get('fim','')
    limites(inicio);limites(fim)
    if inicio>fim or inicio[:4]!=fim[:4]:raise ValueError('Escolha um intervalo dentro do mesmo ano.')
    conta=request.form.get('conta','5.2')
    if not fetch("SELECT 1 FROM contas WHERE conta_id=%s AND grupo='resultado' AND analitica=true",(conta,)):raise ValueError('Escolha uma conta analítica de resultado.')
    v=Decimal(request.form.get('valor','').replace(',','.'))
    if not v.is_finite() or not -10000000<=v<=10000000 or v.as_tuple().exponent<-2:raise ValueError('Use valor de até 10 milhões, com duas casas. Crédito negativo; débito positivo.')
    cents=int(v*100)
    with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT competencia,valor_dc_centavos FROM orcamento WHERE conta_id=%s AND competencia BETWEEN %s AND %s ORDER BY competencia FOR UPDATE',(conta,inicio,fim))
        antes=[dict(x) for x in cur.fetchall()]
        for mes in range(int(inicio[5:]),int(fim[5:])+1):
            cur.execute('INSERT INTO orcamento VALUES(%s,%s,%s) ON CONFLICT(competencia,conta_id) DO UPDATE SET valor_dc_centavos=excluded.valor_dc_centavos',(inicio[:4]+f'-{mes:02}',conta,cents))
        cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Premissa: serviços de terceiros',Json(antes),Json({'mensal_centavos':cents,'inicio':inicio,'fim':fim})))

@pages.post('/dre/reclassificar')
@login_required
def reclassificar():
    comp=request.form.get('competencia','');destino=request.form.get('destino','').strip()
    destino={'Estrutura':'estrutura','Custos de serviços':'custos_servicos'}.get(destino,destino)
    try:limites(comp)
    except ValueError as e:abort(400,description=str(e))
    if destino not in ('estrutura','custos_servicos'):abort(400,description='Destino deve ser estrutura ou custos_servicos.')
    with connection() as conn,conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(20260912)')
        cur.execute('SELECT destino FROM reclassificacoes WHERE competencia=%s AND conta_id=%s',(comp,'5.2'));old=cur.fetchone()
        cur.execute('INSERT INTO reclassificacoes VALUES(%s,%s,%s) ON CONFLICT(competencia,conta_id) DO UPDATE SET destino=excluded.destino',(comp,'5.2',destino))
        cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Reclassificação gerencial',Json({'competencia':comp,'destino':old[0] if old else 'custos_servicos'}),Json({'competencia':comp,'destino':destino})))
    flash('DRE gerencial atualizada. Lançamentos e resultado total preservados.','success')
    return redirect(url_for('pages.screen',active='dre',competencia=comp))

def uploaded(field):
    f=request.files.get(field)
    if not f or not f.filename.lower().endswith('.csv'):raise ValueError('Selecione um arquivo CSV.')
    return ler_csv(f.read())
def upload_journal():
    novas,ignored=importar(uploaded('file'))
    flash(f'Importação concluída: {novas} novas linhas; {ignored} já existentes.','success')
def upload_extrato():
    rows=validar_extrato(uploaded('extrato'))
    with connection() as conn,conn.cursor() as cur:
        cur.execute('SELECT extrato FROM conciliacao WHERE id=1 FOR UPDATE');found=cur.fetchone();antes=found[0] if found else []
        cur.execute('INSERT INTO conciliacao(id,extrato) VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET extrato=excluded.extrato',(Json(rows),))
        cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Extrato importado',Json({'linhas':len(antes)}),Json({'linhas':len(rows)})))
    flash('Extrato importado e conciliado.','success')

def csv_response(rows,filename):
    stream=io.StringIO(newline='');keys=[k for k in rows[0] if not k.startswith('_')] if rows else []
    writer=csv.DictWriter(stream,fieldnames=keys,extrasaction='ignore');writer.writeheader()
    for row in rows:
        # Evita fórmulas quando um CSV com texto for aberto em planilha.
        safe={k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()}
        writer.writerow(safe)
    return Response('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="{filename}.csv"'})
@pages.get('/modelo/<kind>')
@login_required
def modelo(kind):
    if kind=='nf':
        base=dict(periodo='2026-08',tipo='saida',participante='12.345.678/0001-95',numero='101',serie='1',data_emissao='2026-08-05')
        itens=[dict(base,descricao='Licença de software',cst_pis='01',cst_cofins='01',cfop='6101',ncm='84713000',cst_icms='00',vl_item='1000.00',vl_bc_icms='1000.00',aliq_icms='18.00',vl_icms='180.00',vl_bc_ipi='1000.00',aliq_ipi='10.00',vl_ipi='100.00',vl_bc_pis='1000.00',aliq_pis='1.65',vl_pis='16.50',vl_bc_cofins='1000.00',aliq_cofins='7.60',vl_cofins='76.00',valor_total='1500.00'),
               dict(base,descricao='Implantação (serviço)',cst_pis='01',cst_cofins='01',cfop='6101',ncm='',cst_icms='',vl_item='500.00',vl_bc_icms='500.00',aliq_icms='18.00',vl_icms='90.00',vl_bc_ipi='',aliq_ipi='',vl_ipi='',vl_bc_pis='500.00',aliq_pis='1.65',vl_pis='8.25',vl_bc_cofins='500.00',aliq_cofins='7.60',vl_cofins='38.00',valor_total='')]
        return csv_response(itens,'modelo_nf')
    if kind=='folha-esocial':
        return csv_response([{'periodo':'2026-08','cpf':'529.982.247-25','rubrica':'SAL001','valor':'3000.00'},
                             {'periodo':'2026-08','cpf':'529.982.247-25','rubrica':'INSS','valor':'330.00'}],'modelo_folha_esocial')
    if kind not in ('lancamentos','extrato'):abort(404)
    rows=json.loads((ROOT/'dados'/f'{kind}.json').read_text(encoding='utf-8'))
    if kind=='extrato':
        refs={x['referencia']:x['documento_id'] for x in json.loads((ROOT/'dados/interno.json').read_text(encoding='utf-8'))}
        rows=[dict(x,referencia=refs.get(x['referencia'],x['referencia'])) for x in rows]
    return csv_response(rows,kind)
@pages.get('/exportar/<active>')
@login_required
def exportar(active):
    if active == 'conciliacao':return redirect(url_for('titulos.exportar', **request.args.to_dict()))
    if active == 'conciliacao-arquivos':return redirect('/conciliacao-arquivos')
    if active not in {x['slug'] for x in NAV}:abort(404)
    try:d=context(active)
    except ValueError as e:abort(400,description=str(e))
    if d.get('quadro'):
        q=d['quadro'];rows=[]
        if active=='balanco':
            for lado in q['balanco_lados']:
                rows += [dict(lado=lado['titulo'],**x) for x in lado['linhas']]
                rows.append({'lado':lado['titulo'],'nome':'TOTAL','tipo':'total','atual':lado['total'],'anterior':lado['anterior']})
        elif active in ('dre','dfc'):
            for x in q['dre_linhas' if active=='dre' else 'dfc_linhas']:
                rows.append({'nome':x['nome'],'tipo':x['tipo'],**dict(zip(q['meses'],x['valores'])),'acumulado':x['acumulado'],'anterior':x.get('anterior')})
        elif active=='dmpl':
            rows=[{'nome':x['nome'],**x['componentes'],'total':x['total']} for x in q['dmpl_linhas']]
        return csv_response(rows,active+'_centavos')
    return csv_response(d['rows'],active+'_centavos')
@pages.get('/api/demonstrativo')
@login_required
def api():
    mov,contas,orc=source()
    try:r=demonstrativo(mov,contas,request.args.get('competencia') or (max(x['data'] for x in mov)[:7] if mov else '2026-01'),request.args.get('alcance','mensal'))
    except ValueError as e:abort(400,description=str(e))
    return jsonify(r)

@pages.post('/exportar/tabela.xlsx')
@login_required
def exportar_tabela():
    from core.exportacao import planilha_tabela
    dados=request.get_json(silent=True) or {}
    colunas=dados.get('colunas');linhas=dados.get('linhas')
    if not isinstance(colunas,list) or not 1<=len(colunas)<=100 or not all(isinstance(c,str) and len(c)<=300 for c in colunas):abort(400,description='Colunas inválidas para exportação.')
    if not isinstance(linhas,list) or len(linhas)>5000 or any(not isinstance(l,list) or len(l)!=len(colunas) or any(not isinstance(c,(str,int,float,type(None))) or isinstance(c,str) and len(c)>2000 for c in l) for l in linhas):abort(400,description='Linhas inválidas para exportação.')
    return Response(planilha_tabela(colunas,linhas),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="Relatorio.xlsx"'})

@pages.route('/api/preferencia/<chave>',methods=['GET','POST'])
@login_required
def preferencia(chave):
    if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,120}',chave):abort(400,description='Preferência inválida.')
    email=current_user.get_id()
    if request.method=='GET':
        data=fetch('SELECT valor FROM preferencias_ui WHERE email=%s AND chave=%s',(email,chave))
        return jsonify(data[0]['valor'] if data else {})
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or len(json.dumps(data))>32000:abort(400,description='Preferência inválida.')
    with connection() as conn,conn.cursor() as cur:
        cur.execute('INSERT INTO preferencias_ui(email,chave,valor) VALUES(%s,%s,%s) ON CONFLICT(email,chave) DO UPDATE SET valor=excluded.valor',(email,chave,Json(data)))
    return jsonify(ok=True)
