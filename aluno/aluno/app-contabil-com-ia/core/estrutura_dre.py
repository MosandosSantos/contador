"""Estrutura, escolha por cadastro e compatibilidade dos vínculos anteriores."""
SEM_REGRA = '__sem_regra__'
PREVALECE = '__centro__'
LEGADO = '__legado__'


def com_coringa(grupos):
    cadastrados = [dict(g) for g in grupos if g['codigo'] != SEM_REGRA]
    return cadastrados + [{'codigo': SEM_REGRA, 'nome': 'ZZ - SEM REGRA',
                           'ordem': max((int(g['ordem']) for g in cadastrados), default=0)+1,
                           'tipo': 'detalhe', 'automatica': True}]


def vinculos_efetivos(legados, contas_config, centros_config):
    """Conta escolhe linha ou delega ao centro. Ausência não cria regra."""
    configuradas = {c['conta_id'] for c in contas_config}
    result = [dict(v) for v in legados if v['conta_id'] not in configuradas]
    for conta in contas_config:
        if conta['modo'] == 'linha':
            if conta.get('grupo_codigo'):
                result.append({'conta_id': conta['conta_id'], 'centro_id': '', 'grupo_codigo': conta['grupo_codigo']})
        else:
            result.extend({'conta_id': conta['conta_id'], 'centro_id': c['centro_id'], 'grupo_codigo': c['grupo_codigo']}
                          for c in centros_config if c.get('grupo_codigo'))
    return result


def validar_linha(cur, codigo):
    if not codigo:return None
    cur.execute("SELECT 1 FROM dre_grupos WHERE codigo=%s AND tipo='detalhe'", (codigo,))
    if not cur.fetchone():raise ValueError('Selecione uma linha de detalhe da Estrutura DRE gerencial.')
    return codigo


def salvar_conta(cur, conta, destino):
    if destino == LEGADO:
        cur.execute("SELECT 1 FROM dre_vinculos WHERE conta_id=%s AND centro_id<>''", (conta['conta_id'],))
        if not cur.fetchone():raise ValueError('Não há vínculos anteriores específicos para preservar.')
        return
    if not conta['analitica'] or conta['grupo'] != 'resultado':
        if destino:raise ValueError('Linha DRE gerencial só se aplica a contas analíticas de resultado.')
        cur.execute('DELETE FROM dre_contas_config WHERE conta_id=%s', (conta['conta_id'],))
        return
    modo = 'centro' if destino == PREVALECE else 'linha'
    codigo = validar_linha(cur, destino) if modo == 'linha' else None
    cur.execute('''INSERT INTO dre_contas_config(conta_id,modo,grupo_codigo) VALUES(%s,%s,%s)
        ON CONFLICT(conta_id) DO UPDATE SET modo=excluded.modo,grupo_codigo=excluded.grupo_codigo''',
        (conta['conta_id'], modo, codigo))
    # Uma escolha explícita substitui os vínculos anteriores dessa conta.
    cur.execute('DELETE FROM dre_vinculos WHERE conta_id=%s', (conta['conta_id'],))


def salvar_centro(cur, centro_id, destino):
    codigo = validar_linha(cur, destino)
    cur.execute('''INSERT INTO dre_centros_config(centro_id,grupo_codigo) VALUES(%s,%s)
        ON CONFLICT(centro_id) DO UPDATE SET grupo_codigo=excluded.grupo_codigo''', (centro_id, codigo))


def apresentar_contas(contas, configuracoes, legados):
    configs = {c['conta_id']:c for c in configuracoes}
    por_conta = {}
    for v in legados:por_conta.setdefault(v['conta_id'], []).append(v)
    saida=[]
    for c in contas:
        cfg=configs.get(c['conta_id']);antigos=por_conta.get(c['conta_id'], [])
        especificos=[v for v in antigos if v.get('centro_id')]
        if cfg:destino=PREVALECE if cfg['modo']=='centro' else cfg.get('grupo_codigo') or ''
        elif especificos:destino=LEGADO
        else:destino=next((v['grupo_codigo'] for v in antigos if not v.get('centro_id')), '')
        saida.append(dict(c,dre_destino=destino,dre_anteriores=antigos if destino==LEGADO else []))
    return saida
