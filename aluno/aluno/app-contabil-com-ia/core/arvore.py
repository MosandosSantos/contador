"""Percurso da hierarquia cadastrada, sem deduzir classificação financeira por código."""
from collections import defaultdict
from core.plano_contas import nivel_estrutural


def linearizar(contas):
    indice = {str(c['conta_id']): dict(c) for c in contas}
    filhos = defaultdict(list)
    for codigo, conta in indice.items():
        pai = str(conta.get('conta_pai_id') or '')
        if pai and pai not in indice:
            raise ValueError(f'Conta {codigo}: pai {pai} não cadastrado.')
        filhos[pai].append(codigo)
    for itens in filhos.values():
        itens.sort(key=lambda codigo: (int(indice[codigo].get('ordem') or 0), codigo))
    vistos, resultado = set(), []

    def visitar(codigo, nivel, caminho):
        if codigo in caminho:
            raise ValueError(f'Hierarquia circular de contas: {codigo}.')
        nivel_conta = nivel_estrutural(codigo, nivel)
        if max(nivel, nivel_conta) > 20:
            raise ValueError('A hierarquia admite até 20 níveis.')
        vistos.add(codigo)
        conta = indice[codigo]
        if filhos[codigo] and conta.get('analitica') is True:
            raise ValueError(f'Conta {codigo}: uma conta com filhas deve ser sintética.')
        resultado.append(dict(conta, node_id=codigo, parent_id=str(conta.get('conta_pai_id') or ''),
                              level=nivel_conta-1, nivel=nivel_conta, has_children=bool(filhos[codigo])))
        for filha in filhos[codigo]:
            visitar(filha, nivel+1, caminho | {codigo})

    for raiz in filhos['']:
        visitar(raiz, 1, set())
    if len(vistos) != len(indice):
        raise ValueError('A hierarquia contém um ciclo sem conta raiz.')
    return resultado


def com_ancestrais(arvore, selecionadas):
    """Mantém o caminho completo dos resultados da busca, sem alterar os saldos."""
    indice = {c['node_id']: c for c in arvore}
    manter = set(selecionadas)
    for codigo in list(manter):
        while codigo in indice and (codigo := indice[codigo]['parent_id']):
            manter.add(codigo)
    return [c for c in arvore if c['node_id'] in manter]


def descendentes(contas, codigo):
    arvore = linearizar(contas)
    indice = {c['node_id']: c for c in arvore}
    encontrados = {codigo} if codigo in indice else set()
    for conta in arvore:
        if conta['parent_id'] in encontrados:
            encontrados.add(conta['node_id'])
    return encontrados
