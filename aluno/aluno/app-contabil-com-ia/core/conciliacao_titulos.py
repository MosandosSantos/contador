"""Motor puro para conciliar títulos contábeis e financeiros.

Não persiste nem altera lançamentos: o resultado conserva as linhas de origem
para que a interface possa explicar cada pendência.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - tratado com mensagem clara em execução mínima
    load_workbook = None


MAX_REGISTROS = 50_000
MAX_BYTES = 12 * 1024 * 1024
_LADOS = {"contabil", "financeiro"}
_ALIAS = {
    "cliente": {"cliente", "nome", "razao", "razao social", "nome cliente"},
    "cnpj": {"cnpj", "cpf", "cpf cnpj", "cpfcnpj", "documento", "doc"},
    "titulo": {"titulo", "titulo numero", "numero titulo", "nf", "numero", "documento fiscal"},
    "emissao": {"emissao", "data emissao", "dt emissao"},
    "vencimento": {"vencimento", "data vencimento", "dt vencimento"},
    "baixa": {"baixa", "data baixa", "dt baixa", "recebimento"},
    "valor": {"valor", "valor titulo", "valor recebido", "vl", "total"},
}


def _cabecalho(valor: object) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _texto(valor: object, campo: str, linha: int) -> str:
    texto = str(valor or "").strip()
    if not texto:
        raise ValueError(f"Linha {linha}: {campo} é obrigatório.")
    return texto


def _normalizar_texto(valor: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", valor).casefold().split())


def _normalizar_documento(valor: str) -> str:
    # Mantém letras para os identificadores sintéticos usados no material didático.
    normalizado = re.sub(r"[^A-Za-z0-9]+", "", unicodedata.normalize("NFKC", valor)).upper()
    if not normalizado:
        raise ValueError("CNPJ/CPF sem caracteres identificadores.")
    return normalizado


def _centavos(valor: object, linha: int) -> int:
    if isinstance(valor, bool) or valor is None or str(valor).strip() == "":
        raise ValueError(f"Linha {linha}: Valor é obrigatório e monetário.")
    if isinstance(valor, Decimal):
        numero = valor
    elif isinstance(valor, (int, float)):
        numero = Decimal(str(valor))
    else:
        texto = str(valor).strip()
        if texto.upper().startswith("R$"):
            texto = texto[2:].strip()
        if not texto or re.search(r"[A-Za-z$€£]", texto) or " " in texto:
            raise ValueError(f"Linha {linha}: Valor inválido.")
        brasileiro = re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?", texto)
        americano = re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?", texto)
        if "," in texto and "." in texto:
            if texto.rfind(",") > texto.rfind(".") and brasileiro:
                texto = texto.replace(".", "").replace(",", ".")
            elif americano:
                texto = texto.replace(",", "")
            else:
                raise ValueError(f"Linha {linha}: Valor inválido.")
        elif brasileiro and "," in texto:
            texto = texto.replace(",", ".")
        elif americano and "." in texto:
            pass
        elif not re.fullmatch(r"\d+", texto):
            raise ValueError(f"Linha {linha}: Valor inválido.")
        try:
            numero = Decimal(texto)
        except InvalidOperation as erro:
            raise ValueError(f"Linha {linha}: Valor inválido.") from erro
    if not numero.is_finite() or numero < 0:
        raise ValueError(f"Linha {linha}: Valor deve ser não negativo.")
    centavos = (numero * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if numero * 100 != centavos:
        raise ValueError(f"Linha {linha}: Valor tem mais de duas casas decimais.")
    return int(centavos)


def _data(valor: object, campo: str, linha: int) -> str:
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if valor < 1 or int(valor) != valor:
            raise ValueError(f"Linha {linha}: {campo} serial Excel inválida.")
        try:
            # Mesmo marco que o Excel/openpyxl; 60 preserva a compatibilidade
            # com o erro histórico de ano bissexto do próprio Excel.
            return (date(1899, 12, 30) + timedelta(days=int(valor))).isoformat()
        except OverflowError as erro:
            raise ValueError(f"Linha {linha}: {campo} serial Excel fora do intervalo.") from erro
    texto = str(valor or "").strip()
    if not texto:
        raise ValueError(f"Linha {linha}: {campo} é obrigatório.")
    for formato in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Linha {linha}: {campo} inválida; use AAAA-MM-DD ou DD/MM/AAAA.")


def _mapear_cabecalhos(cabecalhos: list[object], lado: str) -> dict[str, int]:
    encontrados: dict[str, int] = {}
    for indice, nome in enumerate(cabecalhos):
        chave = _cabecalho(nome)
        for destino, aliases in _ALIAS.items():
            if chave in aliases:
                if destino in encontrados:
                    raise ValueError(f"Cabeçalho repetido para {destino}.")
                encontrados[destino] = indice
                break
    obrigatorios = {"cliente", "cnpj", "titulo", "valor"}
    obrigatorios.add("baixa" if lado == "financeiro" else "emissao")
    faltantes = obrigatorios - set(encontrados)
    if faltantes:
        raise ValueError("Cabeçalho ausente: " + ", ".join(sorted(faltantes)) + ".")
    return encontrados


def _normalizar_linha(valores: list[object], campos: dict[str, int], lado: str, linha: int) -> dict:
    def pegar(nome: str) -> object:
        indice = campos.get(nome)
        return valores[indice] if indice is not None and indice < len(valores) else None
    cliente = _texto(pegar("cliente"), "Cliente", linha)
    cnpj = _texto(pegar("cnpj"), "CNPJ/CPF", linha)
    titulo = _texto(pegar("titulo"), "Título", linha)
    registro = {
        "id_origem": f"{lado}:{linha}", "linha_origem": linha, "lado": lado,
        "cliente": cliente, "cnpj": cnpj, "titulo": titulo,
        "cliente_normalizado": _normalizar_texto(cliente),
        "cnpj_normalizado": _normalizar_documento(cnpj),
        "titulo_normalizado": _normalizar_texto(titulo),
        "valor_centavos": _centavos(pegar("valor"), linha),
        "emissao": None, "vencimento": None, "baixa": None,
    }
    if lado == "contabil":
        registro["emissao"] = _data(pegar("emissao"), "Emissão", linha)
        if "vencimento" in campos:
            registro["vencimento"] = _data(pegar("vencimento"), "Vencimento", linha)
    else:
        registro["baixa"] = _data(pegar("baixa"), "Baixa", linha)
    return registro


def _linhas_csv(raw: bytes) -> list[list[object]]:
    texto = None
    for codificacao in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            texto = raw.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("CSV não pôde ser lido como UTF-8 ou Windows-1252.")
    try:
        dialecto = csv.Sniffer().sniff(texto[:8192], delimiters=";,\t,")
    except csv.Error:
        dialecto = csv.excel
        dialecto.delimiter = ";"
    linhas = list(csv.reader(io.StringIO(texto), dialecto))
    if not linhas:
        raise ValueError("CSV vazio.")
    return linhas


def _linhas_xlsx(raw: bytes) -> list[list[object]]:
    if load_workbook is None:
        raise ValueError("Leitura XLSX requer openpyxl.")
    try:
        livro = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
    except Exception as erro:
        raise ValueError("XLSX inválido.") from erro
    try:
        planilha = livro.active
        linhas = []
        for linha in planilha.iter_rows():
            if any(c.data_type == "f" for c in linha):
                raise ValueError("XLSX com fórmula não é aceito no relatório de conciliação.")
            valores = [c.value for c in linha]
            # Conservar a posição física mesmo quando a linha está vazia.
            # O filtro de vazios só acontece depois de atribuir linha_origem.
            linhas.append(valores)
            if len(linhas) > MAX_REGISTROS + 1:
                raise ValueError("Relatório excede 50.000 linhas.")
        return linhas
    finally:
        livro.close()


def ler_relatorio(raw: bytes, filename: str, lado: str) -> list[dict]:
    """Lê um relatório CSV/XLSX, valida-o e devolve suas linhas preservadas."""
    if lado not in _LADOS:
        raise ValueError("lado deve ser 'contabil' ou 'financeiro'.")
    if not isinstance(raw, bytes) or not filename:
        raise ValueError("Arquivo inválido.")
    if len(raw) > MAX_BYTES:
        raise ValueError("Arquivo excede o limite de 12 MB.")
    extensao = Path(filename).suffix.casefold()
    if extensao == ".csv":
        linhas = _linhas_csv(raw)
    elif extensao == ".xlsx":
        linhas = _linhas_xlsx(raw)
    else:
        raise ValueError("Formato não aceito; envie CSV ou XLSX.")
    if len(linhas) < 2:
        raise ValueError("Relatório vazio.")
    if len(linhas) - 1 > MAX_REGISTROS:
        raise ValueError("Relatório excede 50.000 registros.")
    campos = _mapear_cabecalhos(linhas[0], lado)
    resultado = []
    for numero, valores in enumerate(linhas[1:], 2):
        if not any(valor is not None and str(valor).strip() for valor in valores):
            continue
        if len(valores) > len(linhas[0]):
            raise ValueError(f"Linha {numero}: mais colunas que o cabeçalho.")
        resultado.append(_normalizar_linha(valores, campos, lado, numero))
    if not resultado:
        raise ValueError("Relatório vazio.")
    return resultado


def _resultado(contabil: list[dict], financeiro: list[dict], status: str, motivo: str) -> dict:
    c = contabil[0] if contabil else None
    f = financeiro[0] if financeiro else None
    vc = sum(l["valor_centavos"] for l in contabil) if contabil else None
    vf = sum(l["valor_centavos"] for l in financeiro) if financeiro else None
    return {
        "cliente": (c or f)["cliente"], "titulo": (c or f)["titulo"],
        "cnpj_contabil": c["cnpj"] if c else None, "cnpj_financeiro": f["cnpj"] if f else None,
        "vc_centavos": vc, "vf_centavos": vf,
        "diferenca_centavos": vc - vf if vc is not None and vf is not None else None,
        "st": status, "motivo": motivo,
        "contabil": contabil, "financeiro": financeiro,
        "origens_contabil": [l["id_origem"] for l in contabil],
        "origens_financeiro": [l["id_origem"] for l in financeiro],
    }


def _agrupar(linhas: list[dict], chave) -> dict[tuple, list[dict]]:
    agrupado: dict[tuple, list[dict]] = defaultdict(list)
    for linha in linhas:
        agrupado[chave(linha)].append(linha)
    return agrupado


def conciliar(contabil: list[dict], financeiro: list[dict], tolerancia_centavos: int = 1) -> dict:
    """Cruza relatórios já normalizados sem nunca descartar uma linha de origem."""
    if not isinstance(tolerancia_centavos, int) or tolerancia_centavos < 0:
        raise ValueError("tolerancia_centavos deve ser inteiro não negativo.")
    contabil, financeiro = list(contabil), list(financeiro)
    por_chave_c = _agrupar(contabil, lambda l: (l["titulo_normalizado"], l["cnpj_normalizado"]))
    por_chave_f = _agrupar(financeiro, lambda l: (l["titulo_normalizado"], l["cnpj_normalizado"]))
    usados_c, usados_f, resultado = set(), set(), []
    for chave in sorted(set(por_chave_c) | set(por_chave_f)):
        cs, fs = por_chave_c.get(chave, []), por_chave_f.get(chave, [])
        if len(cs) == len(fs) == 1:
            c, f = cs[0], fs[0]
            usados_c.add(c["id_origem"]); usados_f.add(f["id_origem"])
            diferenca = c["valor_centavos"] - f["valor_centavos"]
            resultado.append(_resultado([c], [f], "ok" if abs(diferenca) <= tolerancia_centavos else "dif", "Título e CNPJ/CPF únicos nos dois relatórios."))
        elif len(cs) > 1 or len(fs) > 1:
            for linha in cs: usados_c.add(linha["id_origem"])
            for linha in fs: usados_f.add(linha["id_origem"])
            resultado.append(_resultado(cs, fs, "duplicado", "Há mais de uma linha para o mesmo título e CNPJ/CPF; nenhuma foi pareada."))

    restantes_c = [l for l in contabil if l["id_origem"] not in usados_c]
    restantes_f = [l for l in financeiro if l["id_origem"] not in usados_f]
    titulos_c = _agrupar(restantes_c, lambda l: (l["titulo_normalizado"],))
    titulos_f = _agrupar(restantes_f, lambda l: (l["titulo_normalizado"],))
    for titulo in sorted(set(titulos_c) & set(titulos_f)):
        cs, fs = titulos_c[titulo], titulos_f[titulo]
        if len(cs) == len(fs) == 1 and cs[0]["cnpj_normalizado"] != fs[0]["cnpj_normalizado"]:
            c, f = cs[0], fs[0]
            usados_c.add(c["id_origem"]); usados_f.add(f["id_origem"])
            resultado.append(_resultado([c], [f], "cnpj", "Mesmo título com CNPJ/CPF diferente; exige investigação cadastral."))
        else:
            for linha in cs: usados_c.add(linha["id_origem"])
            for linha in fs: usados_f.add(linha["id_origem"])
            resultado.append(_resultado(cs, fs, "ambiguo", "Há mais de um candidato com o mesmo título; nenhuma associação foi presumida."))
    for linha in contabil:
        if linha["id_origem"] not in usados_c:
            resultado.append(_resultado([linha], [], "aberto", "Título presente somente no Contábil."))
    for linha in financeiro:
        if linha["id_origem"] not in usados_f:
            resultado.append(_resultado([], [linha], "nlanc", "Título presente somente no Financeiro."))

    por_status = {}
    for status in ("ok", "dif", "aberto", "nlanc", "cnpj", "duplicado", "ambiguo"):
        linhas = [l for l in resultado if l["st"] == status]
        por_status[status] = {
            "quantidade": len(linhas),
            "contabil_centavos": sum(l["vc_centavos"] or 0 for l in linhas),
            "financeiro_centavos": sum(l["vf_centavos"] or 0 for l in linhas),
            "diferenca_absoluta_centavos": sum(abs(l["diferenca_centavos"] or 0) for l in linhas),
        }
    return {"linhas": resultado, "resumo": {
        "quantidade_contabil": len(contabil), "quantidade_financeiro": len(financeiro),
        "total_contabil_centavos": sum(l["valor_centavos"] for l in contabil),
        "total_financeiro_centavos": sum(l["valor_centavos"] for l in financeiro),
        "tolerancia_centavos": tolerancia_centavos, "por_status": por_status,
    }}
