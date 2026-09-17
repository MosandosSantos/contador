"""Estrutura inicial explícita da DRE, aplicada somente por ação do usuário."""

GRUPOS_REFERENCIA = (
    ('receita_bruta', 'Receita bruta', 10, 'detalhe'),
    ('deducoes', 'Deduções da receita', 20, 'detalhe'),
    ('receita_liquida', 'Receita líquida', 30, 'subtotal'),
    ('custos_servicos', 'Custos dos serviços', 40, 'detalhe'),
    ('lucro_bruto', 'Lucro bruto', 50, 'subtotal'),
    ('pessoal', 'Despesas com pessoal', 60, 'detalhe'),
    ('estrutura', 'Despesas de estrutura', 70, 'detalhe'),
    ('ebitda', 'EBITDA', 80, 'subtotal'),
    ('depreciacao', 'Depreciação', 90, 'detalhe'),
    ('ebit', 'Resultado operacional', 100, 'subtotal'),
    ('financeiro', 'Resultado financeiro', 110, 'detalhe'),
    ('resultado_antes_tributos', 'Resultado antes dos tributos', 120, 'subtotal'),
    ('tributos_resultado', 'Tributos sobre o resultado', 130, 'detalhe'),
    ('resultado_liquido', 'Resultado líquido', 140, 'subtotal'),
)


def instalar_referencia(cur):
    """Instala o ponto de partida uma vez, sem tocar em cadastro existente."""
    cur.execute('SELECT pg_advisory_xact_lock(20260911)')
    cur.execute('SELECT count(*) AS quantidade FROM dre_grupos')
    grupos = cur.fetchone()
    if grupos['quantidade'] if isinstance(grupos, dict) else grupos[0]:
        raise ValueError('Já existem grupos DRE cadastrados; a estrutura de referência não foi aplicada.')
    cur.execute('SELECT count(*) AS quantidade FROM dre_vinculos')
    vinculos = cur.fetchone()
    if vinculos['quantidade'] if isinstance(vinculos, dict) else vinculos[0]:
        raise ValueError('Já existem vínculos DRE cadastrados; a estrutura de referência não foi aplicada.')
    for grupo in GRUPOS_REFERENCIA:
        cur.execute('INSERT INTO dre_grupos(codigo,nome,ordem,tipo) VALUES(%s,%s,%s,%s)', grupo)
    cur.execute('''INSERT INTO dre_vinculos(conta_id,centro_id,grupo_codigo)
                   SELECT c.conta_id,'',g.codigo
                     FROM contas c
                     JOIN dre_grupos g ON g.codigo=c.linha_dre
                    WHERE c.grupo='resultado' AND c.analitica=true AND g.tipo='detalhe'
                   ON CONFLICT(conta_id,centro_id) DO NOTHING''')
    return {'grupos_criados': len(GRUPOS_REFERENCIA), 'vinculos_criados': cur.rowcount}
