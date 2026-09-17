"""Recortes explícitos de Balanço, DRE e DMPL a partir do mesmo diário."""
from datetime import date,timedelta
from calendar import monthrange
from core.balancete import intervalo,fins_de_mes
from core.calculos import demonstrativo,componentes_pl
from core.quadros import CANONICA,DERIVADAS,_valor_linha,_balanco_lados


def _normalizar_dre(linhas):
    if not linhas:return None
    conhecidas={k for k,_,_ in CANONICA}-DERIVADAS-{'outras_linhas'}
    saida={k:v for k,v in linhas.items() if k in conhecidas}
    extras=sum(v for k,v in linhas.items() if k not in conhecidas)
    if any(k not in conhecidas for k in linhas):saida['outras_linhas']=extras
    return saida


def _dmpl_por_ano(mov,contas,inicio,fim):
    """Fechamentos anuais encadeados; mutações nunca atravessam o exercício."""
    secoes=[]
    for ano in range(int(inicio[:4]),int(fim[:4])+1):
        de=max(inicio,f'{ano}-01-01');ate=min(fim,f'{ano}-12-31')
        anterior=(date.fromisoformat(de)-timedelta(days=1)).isoformat()
        dmpl=demonstrativo(mov,contas,ate[:7],intervalo_datas=(de,ate))['dmpl']
        def linha(nome,tipo,componentes,data=None):
            return {'ano':ano,'data_de':de,'data_ate':ate,'nome':nome,'tipo':tipo,
                    'data':data,'componentes':componentes,'total':sum(componentes.values())}
        linhas=[linha('Saldo anterior','saldo',dmpl['inicio'],anterior)]
        linhas.extend(linha(nome,'movimento',v) for nome,v in dmpl['movimentos'].items())
        linhas.append(linha('Saldo final','saldo',dmpl['fim'],ate))
        secoes.append({'ano':ano,'inicio':de,'fim':ate,'data_anterior':anterior,'linhas':linhas})
    return secoes


def construir(mov,contas,data_de,data_ate):
    inicio,fim=intervalo(data_de,data_ate)
    mov=[dict(x,data=str(x['data'])[:10]) for x in mov]
    r=demonstrativo(mov,contas,fim[:7],intervalo_datas=(inicio,fim))
    anterior_data=(date.fromisoformat(inicio)-timedelta(days=1)).isoformat()
    anterior=demonstrativo([x for x in mov if x['data']<inicio],contas,fim[:7])['balanco']
    lados=_balanco_lados(mov,contas,fim[:7],'mensal',saldos_atual=r['balanco'],saldos_anterior=anterior)
    linhas_total=_normalizar_dre(r['dre']['linhas_centavos'])
    periodos=[];mensais=[]
    for ultimo in fins_de_mes(inicio,fim):
        de=max(inicio,ultimo[:7]+'-01');ate=min(fim,ultimo)
        periodos.append({'competencia':ultimo[:7],'inicio':de,'fim':ate})
        mensais.append(_normalizar_dre(demonstrativo(mov,contas,ultimo[:7],intervalo_datas=(de,ate))['dre']['linhas_centavos']))
    def ano_anterior(d):
        valor=date.fromisoformat(d);ano=valor.year-1
        return valor.replace(year=ano,day=min(valor.day,monthrange(ano,valor.month)[1])).isoformat()
    anterior_de,anterior_ate=ano_anterior(inicio),ano_anterior(fim)
    anterior_dre=_normalizar_dre(demonstrativo(mov,contas,anterior_ate[:7],intervalo_datas=(anterior_de,anterior_ate))['dre']['linhas_centavos']) if anterior_de[:4]>='1900' else None
    dre=[]
    for chave,nome,tipo in CANONICA:
        if chave=='outras_linhas' and not any('outras_linhas' in (l or {}) for l in [linhas_total,anterior_dre]+mensais):continue
        dre.append({'chave':chave,'nome':nome,'tipo':tipo,'valores':[_valor_linha(l,chave) for l in mensais],'total':_valor_linha(linhas_total,chave),'anterior':_valor_linha(anterior_dre,chave)})
    receita=_valor_linha(linhas_total,'receita_liquida');lucro=_valor_linha(linhas_total,'resultado')
    kpis=[{'label':'Receita líquida','value':receita},{'label':'EBITDA','value':_valor_linha(linhas_total,'ebitda')},{'label':'Lucro R$','value':lucro},{'label':'Lucro %','value':lucro/receita*100 if receita else None,'percentual':True}]
    dmpl_secoes=_dmpl_por_ano(mov,contas,inicio,fim)
    return {'inicio':inicio,'fim':fim,'data_anterior':anterior_data,'balanco_lados':lados,'dre_linhas':dre,'periodos':periodos,'kpis':kpis,'dmpl_secoes':dmpl_secoes,'dmpl_linhas':[linha for secao in dmpl_secoes for linha in secao['linhas']],'componentes_pl':componentes_pl(contas),'anterior_de':anterior_de,'anterior_ate':anterior_ate,'ultimo':max((x['data'] for x in mov),default=None)}
