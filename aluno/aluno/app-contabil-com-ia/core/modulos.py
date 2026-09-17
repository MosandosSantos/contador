"""Limita acesso e navegação por etapa, preservando o motor contábil original."""
import json
from pathlib import Path
from flask import abort, before_render_template, g, request

RAIZ = Path(__file__).resolve().parents[1]
ROTAS = {
    'conciliacao-arquivos': 'conciliacao', 'conciliacao': 'conciliacao',
    'importar': 'importacao-cadastros', 'historico': 'importacao-cadastros', 'contas': 'importacao-cadastros', 'centros': 'importacao-cadastros', 'limpar': 'importacao-cadastros',
    'empresa': 'importacao-cadastros', 'participantes': 'importacao-cadastros', 'usuarios': 'importacao-cadastros', 'minha-senha': 'importacao-cadastros',
    'balancete': 'balancete', 'razao': 'razao', 'balanco': 'balanco', 'dre': 'dre-referencia',
    'dre-gerencial': 'dre-gerencial', 'grupos-dre': 'dre-gerencial', 'dmpl': 'dmpl',
    'dfc': 'fluxos', 'dfc-direto': 'fluxos', 'dfc-indireto': 'fluxos', 'orcamento': 'orcamento',
    'analise': 'analise-ia', 'configuracao-ia': 'analise-ia',
    'ecf': 'fiscal', 'nf': 'fiscal', 'efd-contribuicoes': 'fiscal', 'efd-icms-ipi': 'fiscal', 'esocial': 'fiscal',
    'relatorio-mensal': 'importacao-cadastros',
}

def ativos():
    if not hasattr(g, 'modulos_ativos'):
        try:
            d = json.loads((RAIZ / 'config/modulos.json').read_text(encoding='utf-8'))
            if d.get('schema') != 2 or not isinstance(d.get('habilitados'), list):
                raise ValueError('Estado inválido')
            g.modulos_ativos = set(d['habilitados'])
        except (OSError, ValueError, TypeError):
            g.modulos_ativos = set()
    return g.modulos_ativos

def disponivel(slug):
    slug = str(slug).split('?', 1)[0].strip('/').split('/')[0]
    return slug in ('', 'home') or ROTAS.get(slug, slug) in ativos()

def filtrar_nav(nav):
    return [i for i in nav if disponivel(i['slug'])]

def filtrar_grupos(grupos):
    return [dict(g, itens=itens) for g in grupos if (itens := filtrar_nav(g['itens']))]

def preparar_home(sender, template, context, **extra):
    if template.name != 'home.html':
        return
    context['atalhos'] = [a for a in context.get('atalhos', []) if disponivel(a['url'])]
    if context['atalhos'] and not disponivel(context['proximo']['url']):
        candidato = next((a for a in reversed(context['atalhos']) if a['url'] != '/analise'), context['atalhos'][0])
        context['proximo'] = {'url': candidato['url'], 'titulo': candidato['titulo'], 'icone': candidato['icone']}

def instalar(app):
    @app.before_request
    def limitar_modulos():
        partes = request.path.strip('/').split('/')
        slug = partes[0]
        if slug == 'exportar' and len(partes) > 1:
            slug = partes[1]
        if slug in ROTAS and not disponivel(slug):
            abort(404)
        if slug == 'modelo' and not disponivel('importar'):
            abort(404)
        if request.path == '/dre/reclassificar' and not disponivel('dre-gerencial'):
            abort(404)
        if slug == 'api':
            api = partes[1] if len(partes) > 1 else ''
            if api in ROTAS and not disponivel(api):
                abort(404)
            if api == 'demonstrativo' and not {'balanco', 'dre-referencia', 'dre-gerencial', 'dmpl', 'fluxos', 'orcamento'} <= ativos():
                abort(404)
            if api == 'preferencia' and len(partes) > 2:
                modulo = partes[2].split('.')[0]
                if modulo in ROTAS and not disponivel(modulo):
                    abort(404)
    before_render_template.connect(preparar_home, app, weak=False)
