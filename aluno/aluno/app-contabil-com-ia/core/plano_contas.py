"""Organização determinística de um catálogo de plano de contas.

Contrato público
---------------
``organizar_contas(contas)`` recebe iteráveis de dicionários que tenham
``conta_id``. Devolve uma nova lista, sem alterar os dicionários recebidos,
preservando suas chaves e acrescentando/normalizando ``conta_pai_id``,
``nivel`` e ``analitica``. A função não cria contas nem descrições.

Pai e tipo explícitos vencem qualquer dedução. Quando faltarem, a dedução só
usa contas já presentes no catálogo: códigos numéricos seguem a máscara das
aulas (1, 2, 3 e 5 caracteres) e códigos pontuados respeitam os separadores.
Assim, ``1.1`` não é pai de ``1.10``. Uma inconsistência estrutural é um erro
pontual; lacunas da máscara viram avisos pela variante interna usada na prévia.
"""
from __future__ import annotations

from collections.abc import Iterable
import re


_MASCARA_AULAS = (1, 2, 3, 5)
_CODIGO_NUMERICO = re.compile(r"^\d+$")
_CODIGO_PONTUADO = re.compile(r"^\d+(?:\.\d+)+$")


def _texto(valor: object) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def nivel_estrutural(conta_id: str, profundidade: int = 1) -> int:
    """Nível derivado do código; o valor informado não altera a estrutura."""
    codigo = _texto(conta_id)
    if _CODIGO_PONTUADO.fullmatch(codigo):
        return len(codigo.split('.'))
    if _CODIGO_NUMERICO.fullmatch(codigo):
        return 1 + sum(tamanho < len(codigo) for tamanho in _MASCARA_AULAS)
    return profundidade


def _booleano(valor: object, conta_id: str) -> bool | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool):
        return valor
    texto = str(valor).strip().casefold()
    if texto in {"1", "true", "sim", "s", "analitica", "analítica"}:
        return True
    if texto in {"0", "false", "nao", "não", "n", "sintetica", "sintética"}:
        return False
    raise ValueError(f"Conta {conta_id}: analitica deve ser verdadeiro ou falso.")


def _nivel_explicito(valor: object, conta_id: str) -> int | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool):
        raise ValueError(f"Conta {conta_id}: nivel inválido.")
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError) as erro:
        raise ValueError(f"Conta {conta_id}: nivel inválido.") from erro
    if numero < 1:
        raise ValueError(f"Conta {conta_id}: nivel deve ser maior que zero.")
    return numero


def _ancestrais_por_mascara(conta_id: str) -> list[str]:
    """Candidatos em ordem do pai mais específico ao menos específico."""
    if _CODIGO_PONTUADO.fullmatch(conta_id):
        partes = conta_id.split(".")
        return [".".join(partes[:indice]) for indice in range(len(partes) - 1, 0, -1)]
    if _CODIGO_NUMERICO.fullmatch(conta_id):
        return [conta_id[:tamanho] for tamanho in reversed(_MASCARA_AULAS) if tamanho < len(conta_id)]
    return []


def organizar_contas(contas: Iterable[dict]) -> list[dict]:
    """Devolve contas com pai, nível e tipo contábil coerentes e verificáveis.

    Ver :func:`organizar_contas_com_avisos` quando a prévia também precisar
    informar lacunas de máscara que não impedem a leitura do arquivo.
    """
    resultado, _ = organizar_contas_com_avisos(contas)
    return resultado


def organizar_contas_com_avisos(contas: Iterable[dict]) -> tuple[list[dict], list[str]]:
    """Como :func:`organizar_contas`, devolvendo também avisos objetivos.

    Avisos descrevem apenas ancestrais esperados pela máscara que não vieram no
    catálogo. Eles não autorizam a criação de um agrupador sem descrição.
    """
    itens: dict[str, dict] = {}
    ordem_entrada: list[str] = []
    for origem in contas:
        conta = dict(origem)
        conta_id = _texto(conta.get("conta_id"))
        if not conta_id:
            raise ValueError("Conta sem código no catálogo.")
        if conta_id in itens:
            raise ValueError(f"Conta repetida no catálogo: {conta_id}.")
        conta["conta_id"] = conta_id
        conta["conta_pai_id"] = _texto(conta.get("conta_pai_id"))
        conta["_analitica_explicita"] = _booleano(conta.get("analitica"), conta_id)
        conta["_nivel_explicito"] = _nivel_explicito(conta.get("nivel"), conta_id)
        itens[conta_id] = conta
        ordem_entrada.append(conta_id)

    # Relações declaradas vencem prefixos. Candidatos de máscara são guardados
    # à parte: eles servem para reconhecer uma estrutura sem tipo explícito,
    # mas não são descendentes finais até que o pai seja realmente escolhido.
    filhos: dict[str, set[str]] = {conta_id: set() for conta_id in itens}
    candidatos_por_mascara: dict[str, set[str]] = {conta_id: set() for conta_id in itens}
    for conta_id, conta in itens.items():
        pai = conta["conta_pai_id"]
        if pai:
            if pai == conta_id:
                raise ValueError(f"Conta {conta_id}: conta pai não pode ser ela própria.")
            if pai not in itens:
                raise ValueError(f"Conta {conta_id}: pai explícito inexistente: {pai}.")
            filhos[pai].add(conta_id)
        else:
            for candidato in _ancestrais_por_mascara(conta_id):
                if candidato in itens:
                    candidatos_por_mascara[candidato].add(conta_id)

    for conta_id, conta in itens.items():
        if conta["conta_pai_id"]:
            continue
        for candidato in _ancestrais_por_mascara(conta_id):
            possivel_pai = itens.get(candidato)
            if possivel_pai is None:
                continue
            if possivel_pai["_analitica_explicita"] is True:
                raise ValueError(
                    f"Conta {conta_id}: pai inferível {candidato} é analítica; informe um pai explícito válido."
                )
            # A máscara só prova o parentesco se o agrupador for sintético
            # explicitamente ou se a própria estrutura completa o tornar pai.
            if (
                possivel_pai["_analitica_explicita"] is False
                or (
                    possivel_pai["_analitica_explicita"] is None
                    and bool(filhos[candidato] or candidatos_por_mascara[candidato])
                )
            ):
                conta["conta_pai_id"] = candidato
                filhos[candidato].add(conta_id)
                break

    # Níveis explícitos não tornam um ciclo aceitável. A validação ocorre
    # depois da inferência para cobrir também a árvore final formada aqui.
    for conta_id in itens:
        vistos: set[str] = set()
        atual = conta_id
        while itens[atual]["conta_pai_id"]:
            if atual in vistos:
                raise ValueError(f"Ciclo na hierarquia de contas: {conta_id}.")
            vistos.add(atual)
            atual = itens[atual]["conta_pai_id"]

    # Uma conta analítica só conflita com filhas finais, nunca com um prefixo
    # descartado porque a filha trouxe pai explícito diferente.
    for conta_id, conta in itens.items():
        if filhos[conta_id] and conta["_analitica_explicita"] is True:
            exemplo = sorted(filhos[conta_id])[0]
            raise ValueError(
                f"Conta {conta_id}: analítica explícita conflita com a descendente {exemplo}."
            )

    for conta_id, conta in itens.items():
        analitica = conta["_analitica_explicita"]
        conta["analitica"] = analitica if analitica is not None else not bool(filhos[conta_id])

    def profundidade(conta_id: str) -> int:
        pai = itens[conta_id]["conta_pai_id"]
        return profundidade(pai) + 1 if pai else 1

    for conta_id in ordem_entrada:
        itens[conta_id]["nivel"] = nivel_estrutural(conta_id, profundidade(conta_id))

    avisos: list[str] = []
    for conta_id in ordem_entrada:
        conta = itens[conta_id]
        if conta["_nivel_explicito"] is not None and conta["_nivel_explicito"] != conta["nivel"]:
            avisos.append(
                f"Conta {conta_id}: nível informado {conta['_nivel_explicito']} substituído pelo nível {conta['nivel']} da estrutura."
            )
        if conta["_analitica_explicita"] is False and not filhos[conta_id]:
            avisos.append(
                f"Conta {conta_id}: sintética explícita sem descendente no catálogo; confira a origem."
            )
        elif conta["_analitica_explicita"] is None and filhos[conta_id]:
            avisos.append(
                f"Conta {conta_id}: sem tipo explícito; tratada como sintética pelos descendentes existentes."
            )
        if not conta["conta_pai_id"]:
            ausentes = [x for x in _ancestrais_por_mascara(conta_id) if x not in itens]
            if ausentes:
                avisos.append(
                    f"Conta {conta_id}: ancestrais da máscara ausentes ({', '.join(ausentes)}); nenhum pai foi criado."
                )
        del conta["_analitica_explicita"]
        del conta["_nivel_explicito"]
    return [itens[conta_id] for conta_id in ordem_entrada], avisos
