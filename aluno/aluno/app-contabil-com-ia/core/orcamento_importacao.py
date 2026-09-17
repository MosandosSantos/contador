"""Orçamento opcional transportado pelo modelo XLSX, sem virar lançamento."""
from __future__ import annotations

import re


CAMPOS_ORCAMENTO = ("competencia", "conta_id", "valor_dc_centavos")
COMPETENCIA = re.compile(r"^(19|20|21)\d{2}-(0[1-9]|1[0-2])$")


def ler_orcamento(registros):
    """Normaliza a aba ORCAMENTO e preserva centavos/sinal da fonte."""
    if registros is None:
        return None
    saida, chaves = [], set()
    for registro in registros:
        competencia = str(registro.get("competencia") or "").strip()
        conta_id = str(registro.get("conta_id") or "").strip()
        valor = registro.get("valor_dc_centavos")
        if not COMPETENCIA.fullmatch(competencia):
            raise ValueError("ORCAMENTO: competencia deve usar AAAA-MM.")
        if not conta_id:
            raise ValueError("ORCAMENTO: conta_id é obrigatório.")
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise ValueError("ORCAMENTO: valor_dc_centavos deve ser inteiro em centavos.")
        if abs(valor) > 999999999999:
            raise ValueError("ORCAMENTO: valor_dc_centavos fora do limite.")
        chave = (competencia, conta_id)
        if chave in chaves:
            raise ValueError("ORCAMENTO: competencia e conta_id repetidos.")
        chaves.add(chave)
        saida.append(dict(competencia=competencia, conta_id=conta_id, valor_dc_centavos=valor))
    return sorted(saida, key=lambda item: (item["competencia"], item["conta_id"]))


def validar_orcamento(orcamento, contas):
    if orcamento is None:
        return
    catalogo = {str(conta["conta_id"]): conta for conta in contas}
    for item in orcamento:
        conta = catalogo.get(item["conta_id"])
        if not conta:
            raise ValueError("ORCAMENTO: conta não existe no catálogo: " + item["conta_id"])
        if not conta.get("analitica") or conta.get("grupo") != "resultado":
            raise ValueError("ORCAMENTO: informe uma conta analítica de resultado: " + item["conta_id"])


def aplicar_orcamento(cur, orcamento, modo):
    """Aplica somente o que o arquivo oferece, na transação da importação."""
    resumo = dict(linhas=0, aplicadas=0, preservadas=0)
    if orcamento is None:
        return resumo
    resumo["linhas"] = len(orcamento)
    for item in orcamento:
        cur.execute(
            "INSERT INTO orcamento(competencia,conta_id,valor_dc_centavos) VALUES(%s,%s,%s) "
            "ON CONFLICT(competencia,conta_id) DO NOTHING",
            (item["competencia"], item["conta_id"], item["valor_dc_centavos"]),
        )
        if cur.rowcount:
            resumo["aplicadas"] += 1
        elif modo == "acrescentar":
            resumo["preservadas"] += 1
    return resumo


def preencher_faltantes_se_base_igual(cur, contas_modelo, fatos_modelo, orcamento_modelo, competencias=("2026-09", "2026-10", "2026-11", "2026-12")):
    """Helper explícito para recuperar meses faltantes da base fictícia.

    Não deve ser chamado na importação normal. Antes de inserir, exige que o
    catálogo e todos os fatos persistidos sejam exatamente os do modelo; assim
    não usa orçamento didático para completar uma base diferente.
    """
    campos_conta = ("conta_id", "descricao", "grupo", "componente", "linha_dre", "analitica", "conta_pai_id", "ordem", "nivel", "natureza", "classe_bp")
    campos_fato = ("linha_id", "documento_id", "empresa_id", "data", "conta_id", "debito_centavos", "credito_centavos", "tipo", "historico", "origem_id", "centro_id", "atividade_caixa", "rubrica_caixa")

    def registros(rows, campos):
        normalizados = []
        for item in rows:
            valores = item if isinstance(item, dict) else dict(zip(campos, item))
            normalizados.append({
                campo: (str(valores[campo]) if campo == "data" else int(valores[campo]) if campo in ("ordem", "nivel") else valores[campo])
                for campo in campos
            })
        return sorted(normalizados, key=lambda item: tuple(str(item[campo]) for campo in campos))

    cur.execute("SELECT " + ",".join(campos_conta) + " FROM contas")
    if registros(cur.fetchall(), campos_conta) != registros(contas_modelo, campos_conta):
        raise ValueError("A base atual não corresponde ao catálogo do modelo fictício; orçamento não foi preenchido.")
    cur.execute("SELECT " + ",".join(campos_fato) + " FROM lancamentos")
    if registros(cur.fetchall(), campos_fato) != registros(fatos_modelo, campos_fato):
        raise ValueError("A base atual não corresponde aos fatos do modelo fictício; orçamento não foi preenchido.")
    desejados = [item for item in orcamento_modelo if item["competencia"] in competencias]
    validar_orcamento(desejados, contas_modelo)
    inseridos = 0
    for item in desejados:
        cur.execute(
            "INSERT INTO orcamento(competencia,conta_id,valor_dc_centavos) VALUES(%s,%s,%s) "
            "ON CONFLICT(competencia,conta_id) DO NOTHING",
            (item["competencia"], item["conta_id"], item["valor_dc_centavos"]),
        )
        inseridos += cur.rowcount
    return inseridos
