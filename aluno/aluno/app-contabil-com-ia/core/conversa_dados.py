"""Consulta financeira por expressões: referências cadastradas, operações puras e origem.

Sem SQL/eval gerados por modelo. Estoques usam fechamento; fluxos usam o intervalo.
"""
from __future__ import annotations
import calendar
import re
import unicodedata
from datetime import date
from urllib.parse import urlencode
from core.calculos import demonstrativo, contas_folha
from core.quadros import CANONICA, _valor_linha
from core.dre_gerencial import calcular as calcular_gerencial
from core.fluxo_caixa import construir as construir_dfc

BP = {'ativo':'Ativo total','passivo':'Passivo exigível','pl':'Patrimônio líquido (inclui resultado corrente)',
      'ativo_circulante':'Ativo circulante','passivo_circulante':'Passivo circulante',
      'ativo_nao_circulante':'Ativo não circulante','passivo_nao_circulante':'Passivo não circulante',
      'caixa':'Caixa e equivalentes'}
PERIODICIDADES={'mensal','trimestral','anual','periodo'}

def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower()) if not unicodedata.combining(c))

def catalogo(contas, grupos=(), centros=()):
    refs={f'bp.{k}':{'id':f'bp.{k}','titulo':v,'tipo':'saldo'} for k,v in BP.items()}
    for fonte in ('dre','orcado'):
        for codigo,titulo,_ in CANONICA:
            ref=f'{fonte}.{codigo}';refs[ref]={'id':ref,'titulo':titulo+(' (orçado)' if fonte=='orcado' else ''),'tipo':'fluxo'}
    for atividade,nome in [('operacional','Operacional'),('investimento','Investimentos'),('financiamento','Financiamento')]:
        ref='dfc.'+atividade;refs[ref]={'id':ref,'titulo':'Fluxo de caixa '+nome,'tipo':'fluxo'}
    for c in contas:
        codigo=str(c['conta_id']);ref='conta:'+codigo
        refs[ref]={'id':ref,'titulo':codigo+' · '+str(c.get('descricao') or codigo),'tipo':'fluxo' if c.get('grupo')=='resultado' else 'saldo'}
    for g in grupos:
        for fonte in ('gerencial','orcado_gerencial'):
            ref=fonte+':'+str(g['codigo']);refs[ref]={'id':ref,'titulo':str(g['nome'])+' · DRE gerencial'+(' orçada' if fonte.startswith('orcado') else ''),'tipo':'fluxo'}
    return {'referencias':refs,'centros':{str(c['centro_id']):str(c.get('descricao') or c['centro_id']) for c in centros}}

def _data(valor):
    try:d=date.fromisoformat(str(valor))
    except (ValueError,TypeError):raise ValueError('Informe uma data válida no período.') from None
    if not 1900<=d.year<=2199:raise ValueError('Ano fora do intervalo permitido.')
    return d.isoformat()

def deslocar_mes(ano,mes,quantidade):
    n=ano*12+mes-1+quantidade;y,m=divmod(n,12)
    if not 1900<=y<=2199:raise ValueError('Período fora do intervalo permitido.')
    return y,m+1

def fim_mes(ano,mes):return f'{ano:04}-{mes:02}-{calendar.monthrange(ano,mes)[1]:02}'

def ref(codigo):return {'ref':codigo}
def operacao(op,a,b):return {'op':op,'a':a,'b':b}

def legado(plano):
    """Contextos antigos continuam funcionando depois de atualizar a tela."""
    if not isinstance(plano,dict) or 'metrica' not in plano:return plano
    if set(plano)-{'metrica','periodicidade','ano'}:raise ValueError('Contexto inválido.')
    metrica=plano['metrica']
    exp=operacao('dividir',ref('bp.ativo_circulante'),ref('bp.passivo_circulante')) if metrica=='liquidez_corrente' else ref('dre.'+('receita_bruta' if metrica=='faturamento' else metrica))
    return {'series':[{'titulo':{'liquidez_corrente':'Liquidez corrente','faturamento':'Faturamento','receita_liquida':'Receita líquida','resultado':'Resultado do período','ebitda':'EBITDA'}.get(metrica,metrica),'expressao':exp,'formato':'indice' if metrica=='liquidez_corrente' else 'centavos'}],
            'periodicidade':plano.get('periodicidade','mensal'),'periodo':{'ano':plano.get('ano')}}

def validar_expressao(exp, cat, profundidade=0, contador=None):
    contador=contador if contador is not None else [0];contador[0]+=1
    if profundidade>4 or contador[0]>31 or not isinstance(exp,dict):raise ValueError('Fórmula muito longa ou inválida.')
    if set(exp)=={'ref'}:
        if not isinstance(exp['ref'],str) or exp['ref'] not in cat['referencias']:raise ValueError('A fórmula cita uma conta ou componente que não existe na base.')
        return {'ref':exp['ref']},'centavos'
    if set(exp)!={'op','a','b'} or exp['op'] not in ('somar','subtrair','dividir'):raise ValueError('Use somente soma, diferença ou relação entre os componentes disponíveis.')
    a,ua=validar_expressao(exp['a'],cat,profundidade+1,contador);b,ub=validar_expressao(exp['b'],cat,profundidade+1,contador)
    if ua!=ub:raise ValueError('A fórmula combina unidades incompatíveis.')
    return {'op':exp['op'],'a':a,'b':b},'indice' if exp['op']=='dividir' else ua

def validar_plano(plano, cat, ultimo):
    plano=legado(plano)
    if not isinstance(plano,dict) or set(plano)-{'series','periodicidade','periodo','centro_id','comparar_ano_anterior'}:raise ValueError('Plano de consulta inválido.')
    series=plano.get('series')
    if not isinstance(series,list) or not 1<=len(series)<=3:raise ValueError('Selecione até três séries por pergunta.')
    limpas=[]
    for serie in series:
        if not isinstance(serie,dict) or set(serie)-{'titulo','expressao','formato'}:raise ValueError('Série inválida.')
        titulo=serie.get('titulo','')
        if not isinstance(titulo,str) or not 1<=len(titulo.strip())<=120:raise ValueError('Título de análise inválido.')
        exp,unidade=validar_expressao(serie.get('expressao'),cat)
        formato=serie.get('formato',unidade)
        if formato not in ({'indice','percentual'} if unidade=='indice' else {'centavos'}):raise ValueError('Formato incompatível com o cálculo.')
        # Margem é apresentada como porcentagem mesmo se o modelo pedir índice.
        if unidade=='indice' and 'margem' in normalizar(titulo):formato='percentual'
        limpas.append({'titulo':titulo.strip(),'expressao':exp,'formato':formato})
    periodicidade=plano.get('periodicidade','mensal')
    if periodicidade not in PERIODICIDADES:raise ValueError('Periodicidade inválida.')
    periodo=plano.get('periodo',{'ano':int(ultimo[:4])})
    if not isinstance(periodo,dict):raise ValueError('Período inválido.')
    if set(periodo)=={'ano'}:
        ano=periodo['ano']
        if type(ano) is not int or not 1900<=ano<=2199:raise ValueError('Ano inválido.')
    elif set(periodo)=={'ultimos'}:
        n=periodo['ultimos']
        if type(n) is not int or not 1<=n<=36:raise ValueError('Escolha de 1 a 36 períodos recentes.')
    elif set(periodo)=={'inicio','fim'}:
        periodo={'inicio':_data(periodo['inicio']),'fim':_data(periodo['fim'])}
        if periodo['inicio']>periodo['fim']:raise ValueError('Data inicial posterior à final.')
    else:raise ValueError('Informe ano, últimos períodos ou datas inicial e final.')
    centro=plano.get('centro_id','')
    if not isinstance(centro,str) or (centro and centro not in cat['centros']):raise ValueError('Centro de custo inexistente na base.')
    comparar=plano.get('comparar_ano_anterior',False)
    if type(comparar) is not bool:raise ValueError('Comparação inválida.')
    limpo={'series':limpas,'periodicidade':periodicidade,'periodo':periodo,'centro_id':centro,'comparar_ano_anterior':comparar}
    periodos(limpo,ultimo) # Confere extensão antes de calcular.
    return limpo

def periodos(plano,ultimo):
    periodo=plano['periodo'];tipo=plano['periodicidade'];passo={'mensal':1,'trimestral':3,'anual':12,'periodo':1}[tipo]
    if 'ano' in periodo:
        inicio=f"{periodo['ano']}-01-01";fim=f"{periodo['ano']}-12-31"
    elif 'ultimos' in periodo:
        y,m=map(int,ultimo[:7].split('-'))
        mes_ini=((m-1)//passo)*passo+1
        sy,sm=deslocar_mes(y,mes_ini,-(periodo['ultimos']-1)*passo)
        inicio=f'{sy:04}-{sm:02}-01';fim=fim_mes(y,m)
    else:inicio,fim=periodo['inicio'],periodo['fim']
    si,sm=map(int,inicio[:7].split('-'));ey,em=map(int,fim[:7].split('-'))
    if (ey-si)*12+em-sm>=36:raise ValueError('Consulte até 36 meses por vez.')
    if tipo=='periodo':return [(inicio,fim,inicio+' a '+fim)]
    y,m=si,((sm-1)//passo)*passo+1;saida=[]
    while f'{y:04}-{m:02}-01'<=fim:
        fy,fm=deslocar_mes(y,m,passo-1);a=max(inicio,f'{y:04}-{m:02}-01');z=min(fim,fim_mes(fy,fm))
        label=f'{m:02}/{y}' if tipo=='mensal' else (f'{(m-1)//3+1}T/{y}' if tipo=='trimestral' else str(y))
        saida.append((a,z,label));y,m=deslocar_mes(y,m,passo)
    return saida

def referencias(exp):
    if 'ref' in exp:return {exp['ref']}
    return referencias(exp['a'])|referencias(exp['b'])

def formula(exp,cat):
    if 'ref' in exp:return cat['referencias'][exp['ref']]['titulo']
    return '('+formula(exp['a'],cat)+' '+{'somar':'+','subtrair':'−','dividir':'÷'}[exp['op']]+' '+formula(exp['b'],cat)+')'

def resolver_expressao(exp,valores):
    if 'ref' in exp:return valores[exp['ref']]
    a=resolver_expressao(exp['a'],valores);b=resolver_expressao(exp['b'],valores)
    if a is None or b is None:return None
    if exp['op']=='dividir':return a/b if b else None
    return a+b if exp['op']=='somar' else a-b

class Consulta:
    def __init__(self,mov,contas,orcamento=(),grupos=(),vinculos=(),centros=()):
        self.contas=contas;self.folhas=contas_folha(contas);self.por_id={str(c['conta_id']):c for c in contas}
        self.mov=[{**x,'data':str(x['data'])[:10]} for x in mov if x['conta_id'] in self.folhas]
        self.orcamento=orcamento;self.grupos=grupos;self.vinculos=vinculos;self.centros=centros
        self.cat=catalogo(contas,grupos,centros);self.ultimo=max((x['data'] for x in self.mov),default='');self.primeiro=min((x['data'] for x in self.mov),default='')
        self.cache={}
    def descendentes(self,codigo):
        saida=set()
        for folha in self.folhas:
            a=str(folha);vistos=set()
            while a in self.por_id and a not in vistos:
                if a==codigo:saida.add(folha);break
                vistos.add(a);a=str(self.por_id[a].get('conta_pai_id') or '')
        return saida
    def recorte(self,inicio,fim,centro):
        chave=(inicio,fim,centro)
        if chave in self.cache:return self.cache[chave]
        base=[x for x in self.mov if not centro or str(x.get('centro_id') or '')==centro]
        r=demonstrativo(base,self.contas,fim[:7],intervalo_datas=(inicio,fim))
        resultado=[x for x in base if inicio<=x['data']<=fim and self.por_id[str(x['conta_id'])].get('grupo')=='resultado' and x.get('tipo') not in ('abertura','encerramento')]
        # DRE sem abertura/encerramento; balanço preserva todos os tipos.
        dre=demonstrativo(resultado,self.contas,fim[:7],intervalo_datas=(inicio,fim))['dre']['linhas_centavos']
        orc=[{'data':str(x['competencia'])+'-01','conta_id':x['conta_id'],'centro_id':x.get('centro_id') or '',
              'debito_centavos':max(int(x['valor_dc_centavos']),0),'credito_centavos':max(-int(x['valor_dc_centavos']),0),'tipo':'orcamento'}
             for x in self.orcamento if inicio[:7]<=str(x['competencia'])<=fim[:7] and x['conta_id'] in self.folhas and (not centro or str(x.get('centro_id') or '')==centro)]
        ods=demonstrativo(orc,self.contas,fim[:7],intervalo_datas=(inicio[:7]+'-01',fim))['dre']['linhas_centavos']
        ger=calcular_gerencial(resultado,self.contas,self.grupos,self.vinculos,inicio,fim)
        og=calcular_gerencial(orc,self.contas,self.grupos,self.vinculos,inicio[:7]+'-01',fim)
        self.cache[chave]=(base,r,resultado,dre,orc,ods,ger,og);return self.cache[chave]
    def valor(self,codigo,inicio,fim,centro):
        meta=self.cat['referencias'][codigo]
        rota='/balanco' if meta['tipo']=='saldo' else '/dre'
        if codigo.startswith('conta:'):rota='/razao'
        if codigo.startswith('dfc.'):rota='/dfc-direto'
        if codigo.startswith('orcado'):rota='/orcamento'
        if codigo.startswith('gerencial:'):rota='/dre-gerencial'
        query={'data_de':inicio,'data_ate':fim}
        if codigo.startswith('conta:'):query['conta']=codigo.split(':',1)[1]
        if codigo.startswith('gerencial:'):query={'ano':fim[:4],'visao':'mensal'}
        if centro:
            # O Razão permite conferir o centro; os demais relatórios não filtram por ele.
            rota='/razao';query={'data_de':inicio,'data_ate':fim,'centro':centro}
            if codigo.startswith('conta:'):query['conta']=codigo.split(':',1)[1]
        origem=rota+'?'+urlencode(query)
        if not codigo.startswith('orcado') and (inicio>self.ultimo or fim<self.primeiro):return None,origem,'Período fora dos lançamentos importados.'
        base,r,resultado,dre,orc,ods,ger,og=self.recorte(inicio,min(fim,self.ultimo) if not codigo.startswith('orcado') else fim,centro)
        if codigo.startswith('bp.'):
            k=codigo[3:];bp=r['balanco'];saldo=bp['saldos_dc_por_conta']
            if k in ('ativo','passivo','pl'):return bp[k+'_centavos'],origem,''
            if k=='caixa':selecionadas=[c for c in self.contas if c['conta_id'] in self.folhas and c.get('componente')=='caixa'];sinal=1
            else:
                grupo='ativo' if k.startswith('ativo') else 'passivo';classe=k[len(grupo)+1:];sinal=1 if grupo=='ativo' else -1
                relevantes=[c for c in self.contas if c['conta_id'] in self.folhas and c.get('grupo')==grupo]
                permitidas={'circulante','nao_circulante',grupo+'_circulante',grupo+'_nao_circulante'}
                if any((c.get('classe_bp') or c.get('classificacao_balanco')) not in permitidas for c in relevantes):return None,origem,'Há contas sem classificação de balanço.'
                selecionadas=[c for c in relevantes if (c.get('classe_bp') or c.get('classificacao_balanco')) in (classe,grupo+'_'+classe)]
            if not selecionadas:return None,origem,'Não há contas classificadas neste componente.'
            return sinal*sum(saldo.get(c['conta_id'],0) for c in selecionadas),origem,''
        if codigo.startswith('conta:'):
            a=codigo.split(':',1)[1];ids=self.descendentes(a);conta=self.por_id[a]
            sinal=-1 if conta.get('grupo') in ('passivo','pl','resultado') or conta.get('natureza')=='credora' else 1
            if meta['tipo']=='saldo':return sinal*sum(r['balanco']['saldos_dc_por_conta'].get(i,0) for i in ids),origem,''
            if not resultado:return None,origem,'Não há movimento de resultado neste período.'
            return sum(x['credito_centavos']-x['debito_centavos'] for x in resultado if x['conta_id'] in ids),origem,''
        if codigo.startswith('dfc.'):
            dfc=construir_dfc(base,self.contas,inicio,min(fim,self.ultimo),'direto')
            if not any(c.get('componente')=='caixa' for c in self.contas):return None,origem,'Não há contas de caixa classificadas.'
            valor=next(g['total'] for g in dfc['grupos'] if g['codigo']==codigo[4:])
            return valor,origem,' '.join(dfc['avisos'])
        previsto=codigo.startswith('orcado');fatos=orc if previsto else resultado
        if not fatos:return None,origem,'Orçamento não cadastrado neste recorte.' if previsto else 'Não há movimento de resultado neste período.'
        if previsto and (inicio[-2:]!='01' or fim!=fim_mes(int(fim[:4]),int(fim[5:7]))):return None,origem,'Orçamento mensal: não há rateio automático para fração de mês.'
        if previsto:
            meses={a[:7] for a,_,_ in periodos({'periodo':{'inicio':inicio,'fim':fim},'periodicidade':'mensal'},self.ultimo)}
            faltantes=meses-{x['data'][:7] for x in orc}
            if faltantes:return None,origem,'Orçamento ausente em '+', '.join(sorted(faltantes))+'.'
        if codigo.startswith(('gerencial:','orcado_gerencial:')):
            linhas=(og if previsto else ger)['linhas'];v=next((x['valor_centavos'] for x in linhas if x['codigo']==codigo.split(':',1)[1]),None)
        else:v=_valor_linha(ods if previsto else dre,codigo.split('.',1)[1])
        return v,origem,''
    def construir(self,plano):
        plano=validar_plano(plano,self.cat,self.ultimo);quadros=[]
        for serie in plano['series']:
            recortes=periodos(plano,self.ultimo)
            for anterior in ([False,True] if plano['comparar_ano_anterior'] else [False]):
                pontos=[];avisos=[];titulo=serie['titulo']+(' · ano anterior' if anterior else '')
                for inicio,fim,label in recortes:
                    if anterior:
                        def prev(d):
                            y=int(d[:4])-1;m=int(d[5:7]);day=min(int(d[-2:]),calendar.monthrange(y,m)[1]);return f'{y:04}-{m:02}-{day:02}'
                        inicio,fim=prev(inicio),prev(fim);label=label.replace(str(int(fim[:4])+1),fim[:4])
                    valores={};componentes=[];motivos=[]
                    for codigo in sorted(referencias(serie['expressao'])):
                        v,origem,motivo=self.valor(codigo,inicio,fim,plano['centro_id']);valores[codigo]=v
                        componentes.append({'id':codigo,'titulo':self.cat['referencias'][codigo]['titulo'],'valor_centavos':v,'origem':origem})
                        if motivo and motivo not in motivos:motivos.append(motivo)
                    valor=resolver_expressao(serie['expressao'],valores)
                    if valor is not None and serie['formato']=='percentual':valor*=100
                    if valor is None and not motivos:motivos.append('Divisor igual a zero ou componente sem valor; relação não calculada.')
                    usa_real=any(not k.startswith('orcado') for k in valores)
                    parcial=usa_real and (inicio<=self.ultimo<fim or inicio<self.primeiro<=fim)
                    if plano['periodicidade']!='periodo':
                        passo={'mensal':1,'trimestral':3,'anual':12}[plano['periodicidade']]
                        y,m=map(int,inicio[:7].split('-'));primeiro_mes=((m-1)//passo)*passo+1
                        if inicio!=f'{y:04}-{primeiro_mes:02}-01' or fim!=fim_mes(y,primeiro_mes+passo-1):parcial=True
                    pontos.append({'periodo':inicio[:7] if plano['periodicidade']=='mensal' else label,'label':label,'inicio':inicio,'fim':fim,'valor':valor,'anterior':None,'variacao':None,'variacao_percentual':None,'parcial':parcial,
                                   'memoria':{'componentes':componentes,'corte_importado':min(fim,self.ultimo),'motivo':' '.join(motivos)},'url':componentes[0]['origem']})
                    for motivo in motivos:
                        if motivo not in avisos:avisos.append(motivo)
                for anterior_p,atual in zip(pontos,pontos[1:]):
                    a,b=anterior_p['valor'],atual['valor']
                    if a is not None and b is not None and not anterior_p['parcial'] and not atual['parcial']:
                        atual['anterior']=a;atual['variacao']=b-a;atual['variacao_percentual']=100*(b-a)/abs(a) if a else None
                if any(p['parcial'] for p in pontos):avisos.append('Há período parcial; AH não compara períodos incompletos.')
                if plano['centro_id']:avisos.append('Recorte pelo centro '+self.cat['centros'][plano['centro_id']]+'. Contas sem esse centro ficam fora do recorte.')
                quadros.append({'titulo':titulo,'metrica':'expressao','unidade':serie['formato'],'periodicidade':plano['periodicidade'],'ano':int(pontos[-1]['fim'][:4]),'pontos':pontos,'avisos':avisos,
                               'formula':formula(serie['expressao'],self.cat)+(' ×100' if serie['formato']=='percentual' else '')+'. Saldos: fechamento; movimentos: intervalo. AH=(atual−anterior)/|anterior|×100.', 'ultimo_importado':self.ultimo,'primeiro_importado':self.primeiro})
        return quadros

def continuacao_explicita(pergunta,anterior,cat,ultimo):
    """Modificar só o período de uma consulta conhecida dispensa uma nova interpretação."""
    texto=normalizar(pergunta).strip().rstrip('?.!').strip()
    if anterior and re.fullmatch(r'(?:(?:e|agora)\s+)?(?:no\s+)?ano anterior',texto):
        plano=plano_local(pergunta,anterior,cat,ultimo)
        if plano:plano['comparar_ano_anterior']=False
        return plano
    return None


def plano_local(pergunta,anterior,cat,ultimo):
    """Leitura explícita de pedidos simples quando a IA não responde; nunca finge IA."""
    import copy
    t=normalizar(pergunta);t=re.sub(r'\btres\b','3',t)
    exp=None;formato='centavos';titulo='';escolhas=[]
    if ('pl' in re.findall(r'\b\w+\b',t) or 'patrimonio liquido' in t) and 'ativo' in t:
        exp=operacao('dividir',ref('bp.pl'),ref('bp.ativo'));formato='percentual';titulo='PL / Ativo'
    elif 'capital de giro' in t or 'capital circulante liquido' in t:
        exp=operacao('subtrair',ref('bp.ativo_circulante'),ref('bp.passivo_circulante'));titulo='Capital de giro líquido'
    elif 'liquidez' in t:
        if any(x in t for x in ('seca','geral','imediata')):return None
        exp=operacao('dividir',ref('bp.ativo_circulante'),ref('bp.passivo_circulante'));formato='indice';titulo='Liquidez corrente'
    elif 'margem' in t:
        base='ebitda' if 'ebitda' in t else 'lucro_bruto' if 'bruta' in t else 'resultado'
        exp=operacao('dividir',ref('dre.'+base),ref('dre.receita_liquida'));formato='percentual';titulo='Margem '+('EBITDA' if base=='ebitda' else 'bruta' if base=='lucro_bruto' else 'líquida')
    else:
        aliases={'faturamento':'dre.receita_bruta','receita bruta':'dre.receita_bruta','receita liquida':'dre.receita_liquida','ebitda':'dre.ebitda','resultado':'dre.resultado','lucro':'dre.resultado', 'patrimonio liquido':'bp.pl','ativo total':'bp.ativo','passivo total':'bp.passivo'}
        escolhidos=[]
        for nome,codigo in aliases.items():
            if nome in t and codigo not in escolhidos:escolhidos.append(codigo)
        for codigo,meta in cat['referencias'].items():
            if codigo.startswith('conta:'):
                nome=normalizar(meta['titulo'].split(' · ',1)[-1])
                if len(nome)>5 and nome in t and codigo not in escolhidos:escolhidos.append(codigo)
        if 1<=len(escolhidos)<=3:
            escolhas=[{'titulo':'Faturamento' if k=='dre.receita_bruta' else cat['referencias'][k]['titulo'],'expressao':ref(k),'formato':'centavos'} for k in escolhidos]
        elif escolhidos:return None
    if exp:escolhas=[{'titulo':titulo,'expressao':exp,'formato':formato}]
    if ('capital de giro' in t or 'capital circulante liquido' in t) and 'margem' in t:
        base='ebitda' if 'ebitda' in t else 'lucro_bruto' if 'bruta' in t else 'resultado'
        escolhas.append({'titulo':'Margem '+('EBITDA' if base=='ebitda' else 'bruta' if base=='lucro_bruto' else 'líquida'),
            'expressao':operacao('dividir',ref('dre.'+base),ref('dre.receita_liquida')),'formato':'percentual'})
    if not exp and any(x in t for x in ('participacao','relacao','proporcao')):
        # Uma conta específica sobre Ativo total. Nome de sintética contido no da
        # analítica não vira uma segunda série nem uma segunda parcela do cálculo.
        contas=[x for x in escolhas if x['expressao'].get('ref','').startswith('conta:')]
        contas.sort(key=lambda x:len(x['titulo'].split(' · ',1)[-1]),reverse=True)
        if not contas or 'ativo total' not in t:return None
        nome=normalizar(contas[0]['titulo'].split(' · ',1)[-1])
        if any(normalizar(x['titulo'].split(' · ',1)[-1]) not in nome for x in contas[1:]):return None
        escolhas=[{'titulo':contas[0]['titulo']+' / Ativo','expressao':operacao('dividir',contas[0]['expressao'],ref('bp.ativo')),'formato':'percentual'}]
    if not escolhas and not anterior:return None
    if not escolhas and not re.search(r'\b(e|agora|anterior|antes|porque|por que|explique|detalhe|reais|percentual)\b',t):return None
    plano=copy.deepcopy(anterior) if anterior else {'series':escolhas,'periodicidade':'mensal','periodo':{'ano':int(ultimo[:4])}}
    if escolhas:plano['series']=escolhas
    if 'trimestr' in t:plano['periodicidade']='trimestral'
    elif 'mens' in t or 'mes a mes' in t:plano['periodicidade']='mensal'
    recent=re.search(r'ultimos?\s+(\d+)\s+(mes|trimestr|ano)',t)
    anos=re.findall(r'\b(?:19|20|21)\d{2}\b',t)
    if recent:
        plano['periodicidade']={'mes':'mensal','trimestr':'trimestral','ano':'anual'}[recent[2]];plano['periodo']={'ultimos':int(recent[1])}
    elif anos and len(set(anos))==1:plano['periodo']={'ano':int(anos[0])}
    elif 'ano anterior' in t:
        if 'compar' in t:plano['comparar_ano_anterior']=True
        else:
            ps=periodos(plano,ultimo);a,z=ps[0][0],ps[-1][1]
            def prev(d):
                y=int(d[:4])-1;m=int(d[5:7]);return f'{y:04}-{m:02}-{min(int(d[-2:]),calendar.monthrange(y,m)[1]):02}'
            plano['periodo']={'inicio':prev(a),'fim':prev(z)}
    try:return validar_plano(plano,cat,ultimo)
    except ValueError:return None
