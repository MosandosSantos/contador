"""Contrato opcional de estrutura/destinos gerenciais transportados pelo XLSX."""
import re
from core.estrutura_dre import PREVALECE, salvar_conta, salvar_centro

CODIGO = re.compile(r'^[a-z0-9][a-z0-9_.-]{0,63}$')


def destino_planilha(valor):
    texto = str(valor or '').strip()
    if texto.casefold() in ('', 'zz - sem regra'):
        return ''
    if texto.casefold() == 'prevalece dre' or texto == PREVALECE:
        return PREVALECE
    if not CODIGO.fullmatch(texto):
        raise ValueError('Destino DRE inválido: use o código da linha, Prevalece DRE ou deixe em branco.')
    return texto


def ler_estrutura(registros):
    if registros is None:
        return None
    grupos = []
    codigos, ordens = set(), set()
    for r in registros:
        codigo = str(r.get('codigo') or '').strip()
        nome = str(r.get('nome') or '').strip()
        tipo = str(r.get('tipo') or '').strip().casefold()
        try:
            ordem = int(str(r.get('ordem', '')).strip())
        except ValueError:
            raise ValueError('DRE_GERENCIAL: ordem deve ser um número inteiro.')
        if not CODIGO.fullmatch(codigo) or not 1 <= len(nome) <= 120 or not 1 <= ordem <= 99999 or tipo not in ('detalhe', 'subtotal'):
            raise ValueError('DRE_GERENCIAL: confira código, nome, ordem e tipo (detalhe/subtotal).')
        if codigo in codigos or ordem in ordens:
            raise ValueError('DRE_GERENCIAL: código ou ordem repetidos.')
        codigos.add(codigo); ordens.add(ordem)
        grupos.append(dict(codigo=codigo, nome=nome, ordem=ordem, tipo=tipo))
    return sorted(grupos, key=lambda g: g['ordem'])


def extrair_dre(grupos, contas, centros):
    destinos_contas = [dict(conta_id=c['conta_id'], destino=c['dre_destino']) for c in contas if 'dre_destino' in c and c['analitica'] and c['grupo']=='resultado']
    for c in contas:
        if c.get('dre_destino') and (not c['analitica'] or c['grupo']!='resultado'):
            raise ValueError('Destino DRE gerencial só se aplica a contas analíticas de resultado: '+c['conta_id'])
    destinos_centros = [dict(centro_id=c['centro_id'], destino=c['dre_destino']) for c in centros if 'dre_destino' in c]
    ids = [c['centro_id'] for c in centros]
    if len(ids) != len(set(ids)):
        raise ValueError('Centro repetido no catálogo da planilha.')
    if grupos is None and not destinos_contas and not destinos_centros:
        return None
    return dict(grupos=grupos, contas=destinos_contas, centros=destinos_centros)


def validar_dre(dre, grupos_existentes=(), modo='substituir'):
    if dre is None:
        return
    recebidos = dre['grupos']
    grupos = {g['codigo']:g for g in grupos_existentes}
    if recebidos is not None:
        if modo == 'substituir':
            grupos = {g['codigo']:g for g in recebidos}
        else:
            ordens = {g['ordem']:g['codigo'] for g in grupos.values()}
            for g in recebidos:
                if g['codigo'] in grupos:
                    continue  # Acrescentar preserva a definição que o dono já editou.
                if g['ordem'] in ordens:
                    raise ValueError('DRE_GERENCIAL: ordem em uso por outra linha; revise a estrutura antes de acrescentar.')
                grupos[g['codigo']] = g; ordens[g['ordem']] = g['codigo']
    for tipo, chave in (('contas','conta_id'), ('centros','centro_id')):
        for c in dre[tipo]:
            codigo = c['destino']
            if codigo == PREVALECE and tipo == 'contas':
                continue
            if codigo and (codigo not in grupos or grupos[codigo]['tipo'] != 'detalhe'):
                raise ValueError(f"Destino DRE de {c[chave]} não corresponde a uma linha de detalhe: {codigo}.")


def aplicar_dre(cur, dre, modo):
    """Executar na mesma transação da carga, depois de contas/centros e validação."""
    resumo = dict(linhas_criadas=0, contas_aplicadas=0, centros_aplicados=0, destinos_preservados=0)
    if dre is None:
        return resumo
    if dre['grupos'] is not None:
        for g in dre['grupos']:
            cur.execute('INSERT INTO dre_grupos(codigo,nome,ordem,tipo) VALUES(%s,%s,%s,%s) ON CONFLICT(codigo) DO NOTHING', (g['codigo'],g['nome'],g['ordem'],g['tipo']))
            resumo['linhas_criadas'] += cur.rowcount
    for c in dre['contas']:
        if modo == 'acrescentar':
            cur.execute('SELECT 1 FROM dre_contas_config WHERE conta_id=%s UNION ALL SELECT 1 FROM dre_vinculos WHERE conta_id=%s LIMIT 1', (c['conta_id'],c['conta_id']))
            if cur.fetchone():
                resumo['destinos_preservados'] += 1
                continue
        cur.execute('SELECT * FROM contas WHERE conta_id=%s', (c['conta_id'],))
        conta = cur.fetchone()
        if not conta:
            raise ValueError('Conta do destino DRE não existe: '+c['conta_id'])
        salvar_conta(cur,conta,c['destino'])
        resumo['contas_aplicadas'] += 1
    for c in dre['centros']:
        if modo == 'acrescentar':
            cur.execute('SELECT 1 FROM dre_centros_config WHERE centro_id=%s',(c['centro_id'],))
            if cur.fetchone():
                resumo['destinos_preservados'] += 1
                continue
        salvar_centro(cur,c['centro_id'],c['destino'])
        resumo['centros_aplicados'] += 1
    return resumo
