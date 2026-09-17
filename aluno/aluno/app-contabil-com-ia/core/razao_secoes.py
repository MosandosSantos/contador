"""Razão por conta, calculado em centavos e sem alterar a escrituração recebida."""
from datetime import date, datetime
from numbers import Integral

from core.arvore import linearizar


def _intervalo(data_de, data_ate):
    def normalizar(valor, nome):
        if not isinstance(valor, str):
            raise ValueError(f'{nome} deve estar no formato AAAA-MM-DD.')
        try:
            resultado = date.fromisoformat(valor)
        except ValueError:
            raise ValueError(f'{nome} deve ser uma data válida no formato AAAA-MM-DD.') from None
        if not 1900 <= resultado.year <= 2199 or resultado.isoformat() != valor:
            raise ValueError(f'{nome} deve estar entre 1900-01-01 e 2199-12-31.')
        return resultado.isoformat()

    inicio, fim = normalizar(data_de, 'Data De'), normalizar(data_ate, 'Data Até')
    if inicio > fim:
        raise ValueError('Data De deve ser anterior ou igual à Data Até.')
    return inicio, fim


def _data(valor):
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, str):
        try:
            resultado = date.fromisoformat(valor[:10])
        except ValueError:
            raise ValueError('A data do lançamento deve ser válida.') from None
        if len(valor) < 10 or resultado.isoformat() != valor[:10]:
            raise ValueError('A data do lançamento deve estar no formato AAAA-MM-DD.')
        return resultado.isoformat()
    raise ValueError('A data do lançamento deve ser válida.')


def _centavos(valor, campo):
    if isinstance(valor, bool) or not isinstance(valor, Integral):
        raise ValueError(f'{campo} deve ser um inteiro em centavos.')
    return int(valor)


def _selecionadas(arvore, selecionadas):
    indice = {str(conta['conta_id']): conta for conta in arvore}
    filhos = {codigo: [] for codigo in indice}
    for conta in arvore:
        pai = str(conta.get('parent_id') or '')
        if pai:
            filhos[pai].append(str(conta['conta_id']))

    if selecionadas is None:
        return {codigo for codigo, conta in indice.items() if not conta['has_children']}
    if isinstance(selecionadas, (str, bytes)):
        selecionadas = [selecionadas]
    escolhidas = {str(codigo) for codigo in selecionadas}
    desconhecidas = escolhidas - set(indice)
    if desconhecidas:
        raise ValueError('Conta selecionada não cadastrada: ' + ', '.join(sorted(desconhecidas)) + '.')

    resultado = set()
    pendentes = list(escolhidas)
    while pendentes:
        codigo = pendentes.pop()
        if codigo in resultado:
            continue
        resultado.add(codigo)
        pendentes.extend(filhos[codigo])
    return {codigo for codigo in resultado if not indice[codigo]['has_children']}


def _documento_igual(valor, filtro):
    return str(valor or '') == str(filtro or '')


def construir(movimentos, contas, data_de, data_ate, selecionadas=None, centro=None, documento=None):
    """Monta seções do Razão para contas analíticas.

    ``documento`` restringe apenas as linhas mostradas. Saldo anterior, saldo
    acumulado e saldo final continuam sendo o saldo cronológico real da conta
    (no centro selecionado, quando houver), para não transformar o documento
    isolado em um saldo contábil fictício.
    """
    inicio, fim = _intervalo(data_de, data_ate)
    arvore = linearizar(contas)
    indice = {str(conta['conta_id']): conta for conta in arvore}
    conta_ids = _selecionadas(arvore, selecionadas)
    centro_filtro = None if centro is None else str(centro)
    documento_filtro = None if documento in (None, '') else str(documento)

    por_conta = {codigo: [] for codigo in conta_ids}
    for posicao, bruto in enumerate(movimentos):
        if not isinstance(bruto, dict):
            raise ValueError('Cada lançamento deve ser um registro.')
        conta_id = str(bruto.get('conta_id') or '')
        if conta_id not in indice:
            raise ValueError(f'Conta do lançamento não cadastrada: {conta_id or "(vazia)"}.')
        if indice[conta_id]['has_children']:
            raise ValueError(f'Conta sintética {conta_id} recebeu lançamento.')
        if conta_id not in conta_ids:
            continue
        centro_id = str(bruto.get('centro_id') or '')
        if centro_filtro is not None and centro_id != centro_filtro:
            continue
        por_conta[conta_id].append({
            'data': _data(bruto.get('data')),
            'documento_id': str(bruto.get('documento_id') or ''),
            'linha_id': str(bruto.get('linha_id') or ''),
            'historico': str(bruto.get('historico') or ''),
            'centro_id': centro_id,
            'debito_centavos': _centavos(bruto.get('debito_centavos', 0), 'Débito'),
            'credito_centavos': _centavos(bruto.get('credito_centavos', 0), 'Crédito'),
            'campos_brutos': dict(bruto),
            '_posicao': posicao,
        })

    secoes, export_rows = [], []
    for conta in arvore:
        conta_id = str(conta['conta_id'])
        if conta_id not in conta_ids:
            continue
        cronologia = sorted(por_conta[conta_id], key=lambda x: (x['data'], x['documento_id'], x['linha_id'], x['_posicao']))
        saldo_anterior = sum(x['debito_centavos'] - x['credito_centavos'] for x in cronologia if x['data'] < inicio)
        saldo = saldo_anterior
        exibidos = []
        for item in cronologia:
            if item['data'] < inicio:
                continue
            if item['data'] > fim:
                break
            saldo += item['debito_centavos'] - item['credito_centavos']
            if documento_filtro is not None and not _documento_igual(item['documento_id'], documento_filtro):
                continue
            movimento = {k: v for k, v in item.items() if k != '_posicao'}
            movimento['saldo'] = saldo
            movimento['saldo_centavos'] = saldo
            exibidos.append(movimento)

        saldo_final = saldo
        debito = sum(x['debito_centavos'] for x in exibidos)
        credito = sum(x['credito_centavos'] for x in exibidos)
        secao = {
            'conta_id': conta_id,
            'codigo': conta_id,
            'descricao': conta.get('descricao', ''),
            'saldo_anterior': saldo_anterior,
            'movimentos': exibidos,
            'saldo_final': saldo_final,
            'debito': debito,
            'credito': credito,
            'debito_intervalo': sum(x['debito_centavos'] for x in cronologia if inicio <= x['data'] <= fim),
            'credito_intervalo': sum(x['credito_centavos'] for x in cronologia if inicio <= x['data'] <= fim),
        }
        secoes.append(secao)
        # A abertura torna o saldo anterior exportável sem depender da posição visual do thead.
        export_rows.append({
            'tipo_linha': 'saldo_anterior', 'plano_conta_codigo': conta_id,
            'conta_id': conta_id, 'descricao_conta': conta.get('descricao', ''),
            'data': inicio, 'documento_id': '', 'linha_id': '', 'historico': 'Saldo anterior',
            'centro_id': centro_filtro or '', 'debito_centavos': 0, 'credito_centavos': 0,
            'saldo_centavos': saldo_anterior,
        })
        for movimento in exibidos:
            export_rows.append({
                'tipo_linha': 'movimento', 'plano_conta_codigo': conta_id,
                'conta_id': conta_id, 'descricao_conta': conta.get('descricao', ''),
                'data': movimento['data'], 'documento_id': movimento['documento_id'],
                'linha_id': movimento['linha_id'], 'historico': movimento['historico'],
                'centro_id': movimento['centro_id'], 'debito_centavos': movimento['debito_centavos'],
                'credito_centavos': movimento['credito_centavos'], 'saldo_centavos': movimento['saldo_centavos'],
            })
        export_rows.append({
            'tipo_linha': 'saldo_final', 'plano_conta_codigo': conta_id,
            'conta_id': conta_id, 'descricao_conta': conta.get('descricao', ''),
            'data': fim, 'documento_id': '', 'linha_id': '', 'historico': 'Saldo final',
            'centro_id': centro_filtro or '', 'debito_centavos': 0, 'credito_centavos': 0,
            'saldo_centavos': saldo_final,
        })

    return {
        'inicio': inicio, 'fim': fim, 'secoes': secoes, 'export_rows': export_rows,
        'filtros': {'contas': [x['conta_id'] for x in secoes], 'centro': centro_filtro, 'documento': documento_filtro},
        'saldo_acumulado_real': True,
        'aviso_documento': ('Mostrando apenas o documento selecionado; o saldo acumulado considera todos os lançamentos cronológicos da conta no escopo.' if documento_filtro is not None else ''),
    }
