"""Ponto de partida do app: contexto da base e atalhos, sem calcular relatórios."""
from core.db import fetch
from core.nvidia_chat import status
from core.insights import destaques as destaques_da_base


def contexto():
    base = fetch('SELECT count(*) AS lancamentos, min(data) AS inicio, max(data) AS fim FROM lancamentos')[0]
    pendentes = fetch("SELECT count(*) AS total FROM contas WHERE analitica AND grupo='pendente'")[0]['total']
    tem_base = bool(base['lancamentos'])
    if not tem_base:
        proximo = {'url':'/importar','titulo':'Importar minha base','icone':'ph-upload-simple'}
    elif pendentes:
        proximo = {'url':'/contas','titulo':'Classificar contas','icone':'ph-tree-structure'}
    else:
        proximo = {'url':'/dre-gerencial','titulo':'Abrir DRE gerencial','icone':'ph-chart-line'}
    atalhos = [
        {'titulo':'Conciliação','icone':'ph-arrows-left-right','url':'/conciliacao-arquivos','texto':'Cruze os relatórios e encontre diferenças, ausências e duplicidades.'},
        {'titulo':'Importação','icone':'ph-upload-simple','url':'/importar','texto':'Envie a planilha do ERP e confira os lançamentos antes de gravar.'},
        {'titulo':'Cadastros','icone':'ph-tree-structure','url':'/contas','texto':'Organize a árvore de contas e os vínculos com a DRE gerencial.'},
        {'titulo':'Demonstrativos','icone':'ph-table','url':'/balancete','texto':'Do balancete ao documento: acompanhe os saldos e confira a origem.'},
        {'titulo':'Orçado × Realizado','icone':'ph-calendar','url':'/orcamento','texto':'Compare o planejado com o realizado e acompanhe as variações.'},
        {'titulo':'Análise com IA','icone':'ph-sparkle','url':'/analise','texto':'Pergunte aos seus dados. Explore indicadores, gráficos e explicações.'},
    ]
    return dict(active='home',title='Início',base=base,tem_base=tem_base,pendentes=pendentes,
                proximo=proximo,atalhos=atalhos,ia_configurada=status()['configurada'],
                destaques=destaques_da_base(fetch('SELECT data,conta_id,debito_centavos,credito_centavos FROM lancamentos'),
                                            fetch('SELECT conta_id,descricao,analitica,grupo,componente,natureza FROM contas')) if tem_base else [])
