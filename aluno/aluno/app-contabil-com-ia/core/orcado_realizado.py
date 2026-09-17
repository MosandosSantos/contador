"""Comparativo Orçado × Realizado por conta, inteiramente em centavos.

O módulo não conhece banco, rota ou data do computador.  Uma ausência de
lançamento/premissa é representada por ``None``; portanto não há como uma
competência futura virar realizado zero por acidente.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from typing import Any, Iterable


def construir_dre(mov, contas, orcamento, grupos, vinculos, data_de, data_ate, niveis=None, centros=None):
    """O/R por mês na estrutura cadastrada, usando o motor de classificação da DRE."""
    from core.dre_gerencial import calcular, _pais_contas, _resolver_vinculo
    from core.dre_hierarquia import reagrupar_arvore
    from core.estrutura_dre import SEM_REGRA, com_coringa

    inicio, fim = _como_data(data_de), _como_data(data_ate)
    if inicio > fim:
        raise ValueError('Data De deve ser anterior ou igual à Data Até.')
    periodos = _competencias_entre(inicio, fim)
    grupos = com_coringa(grupos)
    cadastro = {str(c['conta_id']): c for c in contas}
    pais, regras = _pais_contas(contas), _resolver_vinculo(vinculos, grupos)
    fontes = {'orcado': [], 'realizado': []}
    for m in mov:
        if inicio <= _como_data(m['data']) <= fim and m.get('tipo') not in ('abertura', 'encerramento'):
            fontes['realizado'].append(m)
    for o in orcamento:
        if o['competencia'] not in periodos:
            continue
        valor = int(o['valor_dc_centavos'])
        fontes['orcado'].append(dict(data=o['competencia']+'-01', conta_id=o['conta_id'],
            centro_id=o.get('centro_id') or '', debito_centavos=max(valor, 0),
            credito_centavos=max(-valor, 0), tipo='orcamento'))
    chaves = [p+':'+fonte for p in periodos for fonte in fontes]
    contribuicoes, calculos = {}, {}
    for fonte, movimentos in fontes.items():
        for p in periodos:
            y, m = map(int, p.split('-'))
            calculos[p+':'+fonte] = calcular(movimentos, contas, grupos, vinculos,
                p+'-01', f'{p}-{calendar.monthrange(y,m)[1]:02}')
        for movimento in movimentos:
            conta_id = str(movimento['conta_id'])
            if cadastro.get(conta_id, {}).get('grupo') != 'resultado':
                continue
            centro = str(movimento.get('centro_id') or '')
            grupo = regras.get(conta_id, {}).get(centro, regras.get(conta_id, {}).get('', SEM_REGRA))
            caminho, vistos, atual = [], set(), conta_id
            while atual in cadastro and atual not in vistos:
                vistos.add(atual); caminho.append(cadastro[atual]); atual = pais.get(atual, '')
            caminho.reverse()
            c = contribuicoes.setdefault((grupo, conta_id, centro), dict(grupo_codigo=grupo,
                contas=caminho, centro_id=centro, valores={k: None for k in chaves}))
            k = str(movimento['data'])[:7]+':'+fonte
            c['valores'][k] = (c['valores'][k] or 0)+int(movimento['credito_centavos'])-int(movimento['debito_centavos'])
    contas_grupos = defaultdict(set)
    for c in contribuicoes.values():
        contas_grupos[c['grupo_codigo']].add(str(c['contas'][-1]['conta_id']))
    linhas = reagrupar_arvore(grupos, contribuicoes.values(), chaves, niveis=niveis, centros=centros, incluir_contas=True)
    for linha in linhas:
        origem = linha.pop('contas_origem', [])
        ids = contas_grupos[linha['node_id'].removeprefix('grupo:')] if linha['nivel']==0 else origem
        naturezas = {cadastro[c].get('natureza') for c in ids}
        natureza = ('despesa' if naturezas=={'devedora'} else 'receita' if naturezas=={'credora'} else 'resultado') if linha['tipo']!='subtotal' else 'resultado'
        linha['natureza_variacao'] = natureza
        if linha['nivel'] == 0:
            codigo = linha['node_id'].removeprefix('grupo:')
            for k, resultado in calculos.items():
                linha['valores'][k] = next(x['valor_centavos'] for x in resultado['linhas'] if x['codigo']==codigo) if resultado['tem_movimentos'] else None
        # Conta sem movimento em mês carregado tem realizado zero. Centro sem
        # orçamento não recebe rateio ou comparação inventada.
        elif 'centro_id' not in linha and linha['tipo'] != 'centro':
            for p in periodos:
                k = p+':realizado'
                if linha['valores'][k] is None and calculos[k]['tem_movimentos']:
                    linha['valores'][k] = 0
        linha['meses'] = {p: _comparativo(linha['valores'][p+':orcado'], linha['valores'][p+':realizado']) for p in periodos}
        linha['total'] = _total_comparativo(linha['meses'].values())
        for valores in [*linha['meses'].values(), linha['total']]:
            valores.update(variacao_apresentacao(valores, natureza))
    meses_total = {p: _comparativo(*[calculos[p+':'+f]['total'] if calculos[p+':'+f]['tem_movimentos'] else None for f in fontes]) for p in periodos}
    avisos = []
    sem_orcamento = [p for p in periodos if not calculos[p+':orcado']['tem_movimentos']]
    if sem_orcamento:
        avisos.append('Sem orçamento em '+', '.join(p[5:]+'/'+p[:4] for p in sem_orcamento)+'.')
    if any(not _mes_integral(inicio, fim, p) for p in periodos):
        avisos.append('O orçamento é mensal integral; o realizado respeita as datas selecionadas.')
    total = _total_comparativo(meses_total.values())
    total.update(variacao_apresentacao(total, 'resultado'))
    return dict(periodos=periodos, linhas=linhas, total=total,
        meses_total=meses_total, avisos=avisos, data_de=inicio.isoformat(), data_ate=fim.isoformat())


def variacao_apresentacao(valores, natureza):
    """Despesa mede aumento/redução do gasto; subtotais medem o resultado.

    O/R conservam os sinais da DRE. O delta contábil também é preservado;
    somente a orientação da variação exibida é invertida nas despesas.
    """
    delta = valores['delta']
    variacao = -delta if delta is not None and natureza=='despesa' else delta
    percentual = valores['delta_percentual']
    if percentual is not None and natureza=='despesa':
        percentual = -percentual
    favoravel = None if variacao in (None, 0) else (variacao<0 if natureza=='despesa' else variacao>0)
    return dict(variacao_centavos=variacao, variacao_percentual=percentual,
                favoravel=favoravel, natureza_variacao=natureza)


def _total_comparativo(meses):
    meses = list(meses)
    orcado = _soma_ou_ausente(m['orcado'] for m in meses)
    realizado = _soma_ou_ausente(m['realizado'] for m in meses)
    base_o = _soma_ou_ausente(m['orcado'] for m in meses if m['comparavel'])
    base_r = _soma_ou_ausente(m['realizado'] for m in meses if m['comparavel'])
    resultado = _comparativo(base_o, base_r)
    return dict(resultado, orcado=orcado, realizado=realizado,
        orcado_comparavel=base_o, realizado_comparavel=base_r)


def _como_data(valor: Any) -> date:
    if isinstance(valor, date):
        return valor
    texto = str(valor)[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise ValueError(f"Data inválida: {valor!r}") from erro


def _competencia(data: date) -> str:
    return f"{data.year:04}-{data.month:02}"


def _competencias_entre(inicio: date, fim: date) -> list[str]:
    ano, mes = inicio.year, inicio.month
    competencias = []
    while (ano, mes) <= (fim.year, fim.month):
        competencias.append(f"{ano:04}-{mes:02}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return competencias


def _mes_integral(inicio: date, fim: date, competencia: str) -> bool:
    ano, mes = map(int, competencia.split("-"))
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    return inicio <= primeiro and fim >= ultimo


def _soma_ou_ausente(valores: Iterable[int | None]) -> int | None:
    presentes = [valor for valor in valores if valor is not None]
    return sum(presentes) if presentes else None


def _percentual(delta: int | None, orcado: int | None) -> float | None:
    if delta is None or orcado in (None, 0):
        return None
    return delta * 100 / abs(orcado)


def _favoravel(delta: int | None) -> bool | None:
    """Na convenção gerencial, Δ positivo é favorável para receita e despesa."""
    return True if delta is not None and delta > 0 else False if delta is not None and delta < 0 else None


def _comparativo(orcado: int | None, realizado: int | None) -> dict[str, Any]:
    comparavel = orcado is not None and realizado is not None
    delta = realizado - orcado if comparavel else None
    return {
        "orcado": orcado,
        "realizado": realizado,
        "delta": delta,
        "delta_percentual": _percentual(delta, orcado),
        "favoravel": _favoravel(delta),
        "comparavel": comparavel,
    }


def construir(mov, contas, orcamento, data_de, data_ate):
    """Constrói um Orçado × Realizado por conta e evolução mensal.

    ``mov`` usa ``data``, ``conta_id``, ``debito_centavos`` e
    ``credito_centavos``. ``orcamento`` usa ``competencia``, ``conta_id`` e
    ``valor_dc_centavos``. Valores contábeis são convertidos para a convenção
    gerencial (receitas positivas e despesas negativas). Orçamentos são
    mensais: mesmo em recorte parcial, a premissa do mês é integral.

    O delta só é calculado quando as duas fontes existem para a mesma conta e
    competência. Assim, totais de delta podem ter cobertura menor que os
    totais brutos de Orçado ou Realizado; os campos ``*_comparavel`` deixam
    essa diferença explícita.
    """
    inicio, fim = _como_data(data_de), _como_data(data_ate)
    if inicio > fim:
        raise ValueError("Data De deve ser anterior ou igual à Data Até.")

    por_conta = {str(conta["conta_id"]): conta for conta in contas}
    competencias = _competencias_entre(inicio, fim)
    resultado_ids = {
        conta_id for conta_id, conta in por_conta.items()
        if conta.get("grupo") == "resultado"
    }

    realizados: dict[tuple[str, str], int] = defaultdict(int)
    realizado_presente: set[tuple[str, str]] = set()
    for movimento in mov:
        conta_id = str(movimento.get("conta_id", ""))
        if conta_id not in resultado_ids or movimento.get("tipo") in {"abertura", "encerramento"}:
            continue
        data = _como_data(movimento.get("data"))
        if inicio <= data <= fim:
            chave = (conta_id, _competencia(data))
            # D - C é o sinal contábil; a DRE gerencial o apresenta invertido.
            realizados[chave] += int(movimento["credito_centavos"]) - int(movimento["debito_centavos"])
            realizado_presente.add(chave)

    orcados: dict[tuple[str, str], int] = defaultdict(int)
    orcado_presente: set[tuple[str, str]] = set()
    for premissa in orcamento:
        conta_id, competencia = str(premissa.get("conta_id", "")), str(premissa.get("competencia", ""))
        if conta_id not in resultado_ids or competencia not in competencias:
            continue
        chave = (conta_id, competencia)
        # A importação persiste o mesmo sinal D-C dos lançamentos.
        orcados[chave] += -int(premissa["valor_dc_centavos"])
        orcado_presente.add(chave)

    contas_com_dados = sorted(
        {conta_id for conta_id, _ in realizado_presente | orcado_presente},
        key=lambda conta_id: (int(por_conta[conta_id].get("ordem") or 0), conta_id),
    )
    linhas = []
    for conta_id in contas_com_dados:
        por_mes = []
        for competencia in competencias:
            chave = (conta_id, competencia)
            por_mes.append(_comparativo(
                orcados[chave] if chave in orcado_presente else None,
                realizados[chave] if chave in realizado_presente else None,
            ))
        orcado = _soma_ou_ausente(x["orcado"] for x in por_mes)
        realizado = _soma_ou_ausente(x["realizado"] for x in por_mes)
        orcado_comparavel = _soma_ou_ausente(x["orcado"] if x["comparavel"] else None for x in por_mes)
        realizado_comparavel = _soma_ou_ausente(x["realizado"] if x["comparavel"] else None for x in por_mes)
        delta = _soma_ou_ausente(x["delta"] for x in por_mes)
        conta = por_conta[conta_id]
        linhas.append({
            "conta_id": conta_id,
            "descricao": conta.get("descricao") or conta_id,
            "orcado": orcado,
            "realizado": realizado,
            "delta": delta,
            "delta_percentual": _percentual(delta, orcado_comparavel),
            "favoravel": _favoravel(delta),
            "comparavel": any(x["comparavel"] for x in por_mes),
            "orcado_comparavel": orcado_comparavel,
            "realizado_comparavel": realizado_comparavel,
            "competencias_comparaveis": [
                competencia for competencia, valores in zip(competencias, por_mes) if valores["comparavel"]
            ],
        })

    meses = []
    for competencia in competencias:
        valores = [
            _comparativo(
                orcados[(conta_id, competencia)] if (conta_id, competencia) in orcado_presente else None,
                realizados[(conta_id, competencia)] if (conta_id, competencia) in realizado_presente else None,
            )
            for conta_id in contas_com_dados
        ]
        orcado = _soma_ou_ausente(x["orcado"] for x in valores)
        realizado = _soma_ou_ausente(x["realizado"] for x in valores)
        orcado_comparavel = _soma_ou_ausente(x["orcado"] if x["comparavel"] else None for x in valores)
        realizado_comparavel = _soma_ou_ausente(x["realizado"] if x["comparavel"] else None for x in valores)
        delta = _soma_ou_ausente(x["delta"] for x in valores)
        meses.append({
            "competencia": competencia,
            "orcamento_mensal_integral": _mes_integral(inicio, fim, competencia),
            "orcado": orcado,
            "realizado": realizado,
            "delta": delta,
            "delta_percentual": _percentual(delta, orcado_comparavel),
            "favoravel": _favoravel(delta),
            "comparavel": any(x["comparavel"] for x in valores),
            "orcado_comparavel": orcado_comparavel,
            "realizado_comparavel": realizado_comparavel,
        })

    total_orcado = _soma_ou_ausente(mes["orcado"] for mes in meses)
    total_realizado = _soma_ou_ausente(mes["realizado"] for mes in meses)
    total_orcado_comparavel = _soma_ou_ausente(mes["orcado_comparavel"] for mes in meses)
    total_realizado_comparavel = _soma_ou_ausente(mes["realizado_comparavel"] for mes in meses)
    total_delta = _soma_ou_ausente(mes["delta"] for mes in meses)

    avisos = []
    if any(not mes["orcamento_mensal_integral"] for mes in meses):
        avisos.append(
            "Orçamento mensal integral: o intervalo contém mês parcial; o Orçado considera o mês completo e o Realizado somente as datas selecionadas."
        )
    if any(mes["orcado"] is None for mes in meses):
        avisos.append("Há meses sem orçamento; ausência é diferente de orçamento zero.")
    if any(item["orcado"] is None for item in linhas):
        avisos.append("Há contas sem orçamento; ausência é diferente de orçamento zero.")
    if any(mes["realizado"] is None for mes in meses):
        avisos.append("Há meses sem realizado disponível; ausência não é tratado como realizado zero.")
    if any(item["realizado"] is None for item in linhas):
        avisos.append("Há contas sem realizado disponível; ausência não é tratado como realizado zero.")
    if any(not mes["comparavel"] and (mes["orcado"] is not None or mes["realizado"] is not None) for mes in meses):
        avisos.append("Δ considera somente conta e mês com Orçado e Realizado disponíveis; não compara período futuro ou lacuna como zero.")

    return {
        "unidade": "centavos",
        "data_de": inicio.isoformat(),
        "data_ate": fim.isoformat(),
        "linhas": linhas,
        "total": {
            "orcado": total_orcado,
            "realizado": total_realizado,
            "delta": total_delta,
            "delta_percentual": _percentual(total_delta, total_orcado_comparavel),
            "favoravel": _favoravel(total_delta),
            "comparavel": any(mes["comparavel"] for mes in meses),
            "orcado_comparavel": total_orcado_comparavel,
            "realizado_comparavel": total_realizado_comparavel,
        },
        "meses": meses,
        "avisos": avisos,
    }
