"""DFC determinística por fatos contábeis, sempre em centavos.

O módulo não consulta nem altera banco.  A rota direta usa exclusivamente a
perna cadastrada como caixa; a indireta parte do resultado e das variações das
contas patrimoniais classificadas.  Quando a classificação necessária não
existe, o valor fica fora do subtotal e ``diferenca``/``avisos`` o expõem.

Referência de apresentação: CPC 03 (R2), itens 18--20 (métodos direto e
indireto) e 43 (transações sem uso de caixa fora da DFC):
https://www.cpc.org.br/CPC/Documentos-Emitidos/Pronunciamentos/Pronunciamento?Id=34
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable


_ORDEM = (
    ("operacional", "Operacionais"),
    ("investimento", "Investimentos"),
    ("financiamento", "Financiamentos"),
)
_ATIVIDADES = {codigo: codigo for codigo, _ in _ORDEM}
_ATIVIDADES.update({"operating": "operacional", "operacional": "operacional",
                    "investment": "investimento", "investing": "investimento",
                    "investimento": "investimento", "financing": "financiamento",
                    "financiamento": "financiamento"})
_SEM_CAIXA = {"abertura", "encerramento", "transferencia_caixa", "transferencia_de_caixa"}
_AJUSTES_PADRAO = {"depreciacao": "Depreciação e amortização", "amortizacao": "Depreciação e amortização"}
_COMPONENTES_GIRO = {
    "clientes", "estoques", "fornecedores", "adiantamentos", "remuneracao",
    "tributos", "tributos_a_recolher", "contas_a_pagar", "contas_a_receber",
}
_COMPONENTES_LONGO_PRAZO = {
    "imobilizado", "redutora_imobilizado", "investimentos", "intangivel",
    "redutora_intangivel", "emprestimos", "financiamentos",
}


def _texto(valor: Any) -> str:
    return str(valor or "").strip().casefold().replace("ç", "c").replace("ã", "a").replace("õ", "o")


def _data(valor: Any, campo: str) -> str:
    if not isinstance(valor, str):
        raise ValueError(f"{campo} deve usar AAAA-MM-DD.")
    try:
        date.fromisoformat(valor)
    except ValueError as erro:
        raise ValueError(f"{campo} inválida: {valor!r}.") from erro
    return valor


def _valor(linha: dict[str, Any]) -> int:
    debito, credito = linha.get("debito_centavos", 0), linha.get("credito_centavos", 0)
    if not isinstance(debito, int) or isinstance(debito, bool) or not isinstance(credito, int) or isinstance(credito, bool):
        raise ValueError("Débito e crédito devem ser inteiros em centavos.")
    return debito - credito


def _atividade(linha: dict[str, Any]) -> str | None:
    return _ATIVIDADES.get(_texto(linha.get("atividade_caixa")))


def _contas_por_id(contas: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indice: dict[str, dict[str, Any]] = {}
    for conta in contas:
        conta_id = conta.get("conta_id")
        if not isinstance(conta_id, str) or not conta_id:
            raise ValueError("Toda conta deve ter conta_id.")
        if conta_id in indice:
            raise ValueError(f"Conta repetida: {conta_id}.")
        indice[conta_id] = conta
    return indice


def _e_caixa(conta: dict[str, Any]) -> bool:
    return _texto(conta.get("componente")) == "caixa" or _texto(conta.get("natureza_dfc")) == "caixa"


def _rotulo(conta: dict[str, Any], conta_id: str) -> str:
    return str(conta.get("descricao") or conta_id)


def _natureza_indireta(conta: dict[str, Any]) -> str:
    """Lê metadado opcional sem converter uma conta desconhecida em giro."""
    bruto = _texto(conta.get("dfc_indireto") or conta.get("classificacao_dfc") or conta.get("natureza_dfc"))
    aliases = {
        "capital_giro": "giro", "capital_de_giro": "giro", "giro": "giro", "operacional": "giro",
        "investimento": "investimento", "financiamento": "financiamento", "nao_caixa": "nao_caixa",
        "sem_caixa": "nao_caixa", "ajuste_nao_caixa": "nao_caixa",
    }
    if bruto in aliases:
        return aliases[bruto]
    componente = _texto(conta.get("componente"))
    if componente in _COMPONENTES_GIRO:
        return "giro"
    if componente in _COMPONENTES_LONGO_PRAZO:
        return "longo_prazo"
    return "desconhecida"


def _linhas_diretas(
    periodo: list[dict[str, Any]], contas: dict[str, dict[str, Any]], avisos: list[str]
) -> dict[str, list[dict[str, Any]]]:
    valores: dict[str, dict[str, int]] = {codigo: defaultdict(int) for codigo, _ in _ORDEM}
    for movimento in periodo:
        conta = contas.get(movimento.get("conta_id"))
        if conta is None:
            avisos.append(f"Conta inexistente no movimento {movimento.get('linha_id') or movimento.get('documento_id') or '?'}.")
            continue
        if not _e_caixa(conta):
            continue
        tipo = _texto(movimento.get("tipo"))
        if tipo in _SEM_CAIXA:
            if tipo == "abertura":
                avisos.append("Saldo de abertura dentro do período não compõe fluxo de caixa.")
            continue
        atividade = _atividade(movimento)
        if atividade is None:
            avisos.append(f"Movimento de caixa sem atividade: {_rotulo(conta, movimento['conta_id'])} em {movimento.get('data')}.")
            continue
        rubrica = str(movimento.get("rubrica_caixa") or "Sem rubrica classificada")
        if rubrica == "Sem rubrica classificada":
            avisos.append(f"Movimento de caixa em {atividade} sem rubrica em {movimento.get('data')}.")
        valores[atividade][rubrica] += _valor(movimento)
    return {
        atividade: [{"nome": nome, "valor": valor} for nome, valor in sorted(rubricas.items())]
        for atividade, rubricas in valores.items()
    }


def _resultado(periodo: list[dict[str, Any]], contas: dict[str, dict[str, Any]]) -> int:
    return -sum(
        _valor(movimento)
        for movimento in periodo
        if contas.get(movimento.get("conta_id"), {}).get("grupo") == "resultado"
        and _texto(movimento.get("tipo")) != "encerramento"
    )


def _ajustes_sem_caixa(
    periodo: list[dict[str, Any]], contas: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    ajustes: dict[str, int] = defaultdict(int)
    for movimento in periodo:
        conta = contas.get(movimento.get("conta_id"))
        if not conta or conta.get("grupo") != "resultado":
            continue
        tipo = _texto(movimento.get("tipo"))
        nome = _AJUSTES_PADRAO.get(tipo)
        if not nome and _natureza_indireta(conta) == "nao_caixa":
            nome = str(conta.get("dfc_ajuste_indireto") or f"Ajuste sem caixa — {_rotulo(conta, movimento['conta_id'])}")
        if nome:
            # Resultado usa crédito como positivo; a despesa não monetária é
            # débito e, portanto, entra aqui com o sinal inverso ao resultado.
            ajustes[nome] += _valor(movimento)
    return [{"nome": nome, "valor": valor} for nome, valor in sorted(ajustes.items()) if valor]


def _variacoes_patrimoniais(
    todos: list[dict[str, Any]], periodo: list[dict[str, Any]], contas: dict[str, dict[str, Any]],
    data_de: str, data_ate: str, avisos: list[str]
) -> list[dict[str, Any]]:
    antes: dict[str, int] = defaultdict(int)
    agora: dict[str, int] = defaultdict(int)
    for movimento in todos:
        conta_id = movimento.get("conta_id")
        if conta_id not in contas:
            continue
        valor = _valor(movimento)
        if movimento["data"] < data_de:
            antes[conta_id] += valor
        if movimento["data"] <= data_ate:
            agora[conta_id] += valor
    linhas: list[dict[str, Any]] = []
    for conta_id, conta in sorted(contas.items()):
        if conta.get("grupo") not in {"ativo", "passivo"} or _e_caixa(conta):
            continue
        delta = agora[conta_id] - antes[conta_id]
        if not delta:
            continue
        natureza = _natureza_indireta(conta)
        if natureza == "giro":
            linhas.append({"nome": f"Variação de {_rotulo(conta, conta_id)}", "valor": -delta, "conta_id": conta_id})
        elif natureza == "desconhecida":
            avisos.append(f"Variação patrimonial sem classificação DFC indireta: {_rotulo(conta, conta_id)} ({delta} centavos).")
        elif natureza == "longo_prazo":
            # Compra/venda de ativo exige fato de caixa classificado; a diferença do saldo não é fluxo por si só.
            avisos.append(f"Variação de longo prazo fora da ponte indireta: {_rotulo(conta, conta_id)} ({delta} centavos).")
    return linhas


def construir(mov, contas, data_de, data_ate, metodo="direto"):
    """Constrói uma DFC para ``data_de`` e ``data_ate`` inclusivas.

    ``metodo`` aceita ``direto`` ou ``indireto``.  Nos dois casos investimento
    e financiamento vêm dos fatos de caixa; no indireto somente o bloco
    operacional é substituído por resultado, ajustes sem caixa e variações de
    capital de giro.  ``diferenca`` é sempre ``variacao - soma dos grupos``.
    Ela não recebe lançamento de ajuste automático.
    """
    data_de, data_ate = _data(data_de, "data_de"), _data(data_ate, "data_ate")
    if data_de > data_ate:
        raise ValueError("data_de deve ser anterior ou igual a data_ate.")
    metodo = _texto(metodo)
    if metodo not in {"direto", "indireto"}:
        raise ValueError("metodo deve ser 'direto' ou 'indireto'.")
    indice = _contas_por_id(contas)
    todos = list(mov)
    for movimento in todos:
        if not isinstance(movimento, dict):
            raise ValueError("Cada movimento deve ser um objeto.")
        _data(movimento.get("data"), "data do movimento")
        _valor(movimento)
    avisos: list[str] = []
    periodo = [movimento for movimento in todos if data_de <= movimento["data"] <= data_ate]
    caixa_ids = {conta_id for conta_id, conta in indice.items() if _e_caixa(conta)}
    if not caixa_ids:
        avisos.append("Nenhuma conta foi marcada como caixa; saldos e fluxos ficaram em zero.")
    caixa_inicial = sum(_valor(movimento) for movimento in todos if movimento.get("conta_id") in caixa_ids and movimento["data"] < data_de)
    caixa_final = sum(_valor(movimento) for movimento in todos if movimento.get("conta_id") in caixa_ids and movimento["data"] <= data_ate)
    diretas = _linhas_diretas(periodo, indice, avisos)
    if metodo == "indireto":
        operacionais = [{"nome": "Resultado do período", "valor": _resultado(periodo, indice)}]
        operacionais.extend(_ajustes_sem_caixa(periodo, indice))
        operacionais.extend(_variacoes_patrimoniais(todos, periodo, indice, data_de, data_ate, avisos))
    else:
        operacionais = diretas["operacional"]
    grupos = []
    for codigo, nome in _ORDEM:
        linhas = operacionais if codigo == "operacional" else diretas[codigo]
        grupos.append({"codigo": codigo, "nome": nome, "total": sum(linha["valor"] for linha in linhas), "linhas": linhas})
    variacao = caixa_final - caixa_inicial
    diferenca = variacao - sum(grupo["total"] for grupo in grupos)
    if diferenca:
        avisos.append(f"DFC não conciliada: diferença de {diferenca} centavos entre a variação de caixa e os grupos apresentados.")
    return {
        "grupos": grupos,
        "caixa_inicial": caixa_inicial,
        "caixa_final": caixa_final,
        "variacao": variacao,
        "diferenca": diferenca,
        "avisos": list(dict.fromkeys(avisos)),
    }
