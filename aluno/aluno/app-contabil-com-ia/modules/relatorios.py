"""Contexto das telas de relatório com filtro explícito e sem gravação de negócio."""
from flask import request
from core.db import fetch
from core.calculos import limites
from core.balancete import intervalo

TITULOS={'balanco':'Balanço patrimonial','razao':'Razão contábil','dre':'DRE de referência','dmpl':'DMPL','dfc-direto':'Fluxo de caixa direto','dfc-indireto':'Fluxo de caixa indireto','orcamento':'Orçado × Realizado'}


def contexto_relatorio(active,mov,contas,orc):
    ultima=max((str(x['data'])[:10] for x in mov),default='2026-01-01')
    comp=request.args.get('competencia') or ultima[:7]
    de,ate=limites(comp,request.args.get('alcance','mensal'))
    if active=='orcamento' and 'competencia' not in request.args:
        de,ate=comp[:4]+'-01-01',comp[:4]+'-12-31'
    de,ate=intervalo(request.args.get('data_de',de),request.args.get('data_ate',ate))
    d=dict(active=active,title=TITULOS[active],data_de=de,data_ate=ate,competencia=ate[:7],alcance='mensal',contas=contas,filtro_action='/'+active,filtro_extra={},rows=[],columns=[],kpis=[],cards=[],audit=[],ultimo_importado=ultima)
    if active in ('balanco','dre','dmpl'):
        from core.relatorios_periodo import construir
        p=construir(mov,contas,de,ate);d.update(periodo=p,template_relatorio='relatorio_periodo.html')
        if active=='balanco':d['rows']=[{'lado':lado['titulo'],'conta_id':x['conta_id'],'descricao':x['nome'],p['data_anterior']:x['anterior'],ate:x['atual']} for lado in p['balanco_lados'] for x in lado['linhas']]
        elif active=='dre':d['rows']=[{'linha':x['nome'],**{m['competencia']:v for m,v in zip(p['periodos'],x['valores'])},'total':x['total'],'anterior':x['anterior']} for x in p['dre_linhas']]
        else:d['rows']=[{'ano':x['ano'],'data_de':x['data_de'],'data_ate':x['data_ate'],'data_saldo':x['data'],'movimentacao':x['nome'],**x['componentes'],'total':x['total']} for x in p['dmpl_linhas']]
    elif active=='razao':
        from core.razao_secoes import construir
        selecionadas=request.args.getlist('contas') or ([request.args['conta']] if request.args.get('conta') else None)
        centro=request.args.get('centro');centro=None if centro=='__todos__' else centro
        documento=request.args.get('documento')
        if centro not in (None,'') and centro not in {x['centro_id'] for x in fetch('SELECT centro_id FROM centros')}:raise ValueError('Centro de custo não cadastrado.')
        razao=construir(mov,contas,de,ate,selecionadas,centro,documento)
        d.update(razao=razao,rows=razao['export_rows'],template_relatorio='razao_secoes.html',filtro_contas=[dict(c,selecionada=c['conta_id'] in (selecionadas or [])) for c in contas],filtro_centros=fetch('SELECT * FROM centros ORDER BY centro_id'),centro_selecionado=centro)
        if documento:d['filtro_extra']['documento']=documento
    elif active.startswith('dfc-'):
        from core.fluxo_caixa import construir
        fluxo=construir(mov,contas,de,ate,active.removeprefix('dfc-'))
        visao=request.args.get('visao','periodo')
        if visao not in ('periodo','meses'):raise ValueError('Escolha Período ou Mês a mês.')
        from core.balancete import fins_de_mes
        meses_fluxo=[{'competencia':fim_mes[:7],'dados':construir(mov,contas,max(de,fim_mes[:7]+'-01'),min(ate,fim_mes),active.removeprefix('dfc-'))} for fim_mes in fins_de_mes(de,ate)] if visao=='meses' else []
        for mes in meses_fluxo:
            mes['disponivel']=mes['competencia']<=ultima[:7]
            for gi,grupo in enumerate(mes['dados']['grupos']):
                nomes={x['nome'] for x in fluxo['grupos'][gi]['linhas']}
                for linha in grupo['linhas']:
                    if linha['nome'] not in nomes:
                        fluxo['grupos'][gi]['linhas'].append(dict(linha,valor=0))
                        nomes.add(linha['nome'])
                if not mes['disponivel']:
                    grupo['total']=None
                    for linha in grupo['linhas']:linha['valor']=None
            if not mes['disponivel']:
                for campo in ('caixa_inicial','caixa_final','variacao','diferenca'):mes['dados'][campo]=None
        d.update(fluxo=fluxo,meses_fluxo=meses_fluxo,visao=visao,template_relatorio='fluxo_caixa.html')
        d['filtro_extra']['visao']=visao
        d['rows']=[{'atividade':g['nome'],'categoria':x['nome'],'valor_centavos':x['valor']} for g in fluxo['grupos'] for x in g['linhas']]
    elif active=='orcamento':
        from core.orcado_realizado import construir_dre
        from core.estrutura_dre import vinculos_efetivos
        from core.balancete import opcoes_niveis, validar_niveis
        from flask_login import current_user
        visao=request.args.get('visao','meses')
        visao={'contas':'periodo','premissas':'meses'}.get(visao,visao)
        if visao not in ('periodo','meses'):raise ValueError('Escolha Do período ou Evolução mensal.')
        grupos=fetch('SELECT codigo,nome,ordem,tipo FROM dre_grupos ORDER BY ordem,codigo')
        vinculos=vinculos_efetivos(fetch('SELECT * FROM dre_vinculos'),fetch('SELECT * FROM dre_contas_config'),fetch('SELECT * FROM dre_centros_config'))
        pref=fetch('SELECT valor FROM preferencias_ui WHERE email=%s AND chave=%s',(current_user.get_id(),'orcamento.hierarquia.v1'))
        if not pref:
            pref=fetch('SELECT valor FROM preferencias_ui WHERE email=%s AND chave=%s',(current_user.get_id(),'dre-gerencial.hierarquia.v1'))
        niveis=None
        if pref:
            try:niveis=validar_niveis(pref[0]['valor'].get('niveis'),contas)
            except (ValueError,AttributeError):pass
        opcoes=opcoes_niveis(contas);selecionados=niveis if niveis is not None else [o['chave'] for o in opcoes]
        por_chave={o['chave']:o for o in opcoes}
        editor=[dict(por_chave[k],selecionado=True) for k in selecionados]+[dict(o,selecionado=False) for o in opcoes if o['chave'] not in selecionados]
        comparativo=construir_dre(mov,contas,orc,grupos,vinculos,de,ate,niveis=selecionados,centros=fetch('SELECT * FROM centros'))
        export=[]
        for l in comparativo['linhas']:
            row={'linha':l['nome'],'nivel':l['nivel']}
            for p,v in (l['meses'].items() if visao=='meses' else [('periodo',l['total'])]):
                row.update({p+'_'+campo:v[campo] for campo in ('orcado','realizado','variacao_centavos','variacao_percentual')})
            export.append(row)
        d.update(comparativo=comparativo,visao=visao,editor_niveis=editor,rows=export,template_relatorio='orcado_realizado.html')
        d['filtro_extra']['visao']=visao
    return d
