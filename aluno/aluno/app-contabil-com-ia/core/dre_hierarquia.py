"""Reagrupamento puro da árvore detalhada da DRE.

Não calcula resultado, orçamento ou AV. Recebe contribuições já classificadas
e apenas escolhe quais dimensões aparecem, na ordem pedida pela apresentação.
"""


def normalizar_niveis(niveis):
    """Valida as dimensões da visão; ``None`` preserva a visão legada."""
    if niveis is None:
        return None
    if not isinstance(niveis, (list, tuple)):
        raise ValueError('Níveis da DRE devem ser uma lista ordenada.')
    resultado = []
    for nivel in niveis:
        chave = str(nivel)
        if chave == 'centro':
            pass
        elif chave.startswith('conta:') and chave[6:].isdigit() and 1 <= int(chave[6:]) <= 20:
            pass
        else:
            raise ValueError(f'Nível estrutural inválido: {chave}.')
        if chave in resultado:
            raise ValueError(f'Nível estrutural repetido: {chave}.')
        resultado.append(chave)
    return resultado


def _cadastro_centros(centros):
    if isinstance(centros, dict):
        return {str(chave): str(valor) for chave, valor in centros.items()}
    return {
        str(item.get('centro_id', '')): str(item.get('descricao') or item.get('nome') or item.get('centro_id') or '')
        for item in (centros or [])
    }


def _ordem_conta(conta):
    try:
        return int(conta.get('ordem') or 100)
    except (TypeError, ValueError):
        return 100


def reagrupar_arvore(grupos, contribuicoes, periodos, niveis=None, centros=None, incluir_contas=False):
    """Monta Grupo DRE -> dimensões escolhidas sem alterar contribuições.

    Cada contribuição contém ``grupo_codigo``, ``contas`` (caminho existente),
    ``centro_id``, ``valores`` e, opcionalmente, ``ano_anterior_centavos``.
    A conta mais específica da contribuição é mantida em todos os nós para que
    o rastreio continue apontando para a folha correta, inclusive com ordem
    invertida como ``conta:5, conta:2``.
    """
    escolhidos = normalizar_niveis(niveis)
    padrao = escolhidos is None
    nomes_centros = _cadastro_centros(centros)
    grupos_ordenados = sorted(grupos, key=lambda item: (int(item['ordem']), str(item['codigo'])))
    grupos_por_codigo = {str(item['codigo']): item for item in grupos_ordenados}
    nodes = {}

    def novo(node_id, parent_id, nivel, tipo, nome, ordem):
        return nodes.setdefault(node_id, {
            'node_id': node_id, 'parent_id': parent_id, 'nivel': nivel,
            'tipo': tipo, 'nome': nome, 'ordem': ordem,
            'valores': {periodo: None for periodo in periodos},
            'ano_anterior_centavos': None, '_filhos': set(), '_contas': set(),
            '_centros': set(), '_filtra_centro': False,
        })

    for grupo in grupos_ordenados:
        codigo = str(grupo['codigo'])
        novo(f'grupo:{codigo}', '', 0, 'subtotal' if grupo['tipo'] == 'subtotal' else 'grupo', grupo['nome'], (int(grupo['ordem']),))

    def somar(node, contribuicao):
        for periodo, valor in contribuicao['valores'].items():
            if valor is not None:
                node['valores'][periodo] = (node['valores'][periodo] or 0) + valor
        anterior = contribuicao.get('ano_anterior_centavos')
        if anterior is not None:
            node['ano_anterior_centavos'] = (node['ano_anterior_centavos'] or 0) + anterior

    for contribuicao in contribuicoes:
        grupo_codigo = str(contribuicao['grupo_codigo'])
        if grupo_codigo not in grupos_por_codigo:
            continue
        caminho = contribuicao.get('contas', [])
        if not caminho:
            continue
        folha = caminho[-1]
        por_nivel = {}
        for indice, conta in enumerate(caminho, 1):
            try:
                nivel_estrutural = int(conta.get('nivel', indice))
            except (TypeError, ValueError):
                nivel_estrutural = indice
            por_nivel.setdefault(nivel_estrutural, conta)
        dimensoes = ([f"conta:{nivel}" for nivel in sorted(por_nivel)] + ['centro']) if padrao else escolhidos
        pai_id = f'grupo:{grupo_codigo}'
        centro_no_caminho = False
        for dimensao in dimensoes:
            profundidade = nodes[pai_id]['nivel'] + 1
            if dimensao == 'centro':
                centro_id = str(contribuicao.get('centro_id') or '')
                node_id = f'{pai_id}:centro:{centro_id}'
                node = novo(node_id, pai_id, profundidade, 'centro', nomes_centros.get(centro_id) or ('Sem centro' if not centro_id else centro_id), nodes[pai_id]['ordem'] + ((0, centro_id),))
                centro_no_caminho = True
            else:
                conta = por_nivel.get(int(dimensao[6:]))
                if conta is None:  # nível ausente não cria subtotal fictício
                    continue
                conta_id = str(conta['conta_id'])
                node_id = f'{pai_id}:conta:{conta_id}'
                node = novo(node_id, pai_id, profundidade, 'conta', f"{conta_id} · {conta.get('descricao') or conta_id}", nodes[pai_id]['ordem'] + ((_ordem_conta(conta), conta_id),))
                node['conta_no_id'] = conta_id
            node['_contas'].add(str(folha['conta_id']))
            node['_centros'].add(str(contribuicao.get('centro_id') or ''))
            node['_filtra_centro'] = node['_filtra_centro'] or centro_no_caminho
            nodes[pai_id]['_filhos'].add(node_id)
            somar(node, contribuicao)
            pai_id = node_id

    if padrao:
        # Contrato anterior: sem centro isolado não vira uma linha extra.
        for node_id, node in list(nodes.items()):
            if node['tipo'] != 'centro' or any(node['_centros']):
                continue
            irmaos = nodes[node['parent_id']]['_filhos']
            if not any(nodes[irmao]['tipo'] == 'centro' and any(nodes[irmao]['_centros']) for irmao in irmaos):
                irmaos.remove(node_id)
                del nodes[node_id]

    saida = []
    for node in sorted(nodes.values(), key=lambda item: item['ordem']):
        node['tem_filhos'] = bool(node['_filhos'])
        if incluir_contas:
            node['contas_origem'] = sorted(node['_contas'])
        # Só publicar filtros capazes de reproduzir exatamente o nó. Assim,
        # um agrupador não aponta por acidente para a última folha somada.
        if len(node['_contas']) == 1:
            node['conta_id'] = next(iter(node['_contas']))
        if node['_filtra_centro'] and len(node['_centros']) == 1:
            node['centro_id'] = next(iter(node['_centros']))
        for chave in ('_filhos', '_contas', '_centros', '_filtra_centro', 'ordem'):
            del node[chave]
        saida.append(node)
    return saida
