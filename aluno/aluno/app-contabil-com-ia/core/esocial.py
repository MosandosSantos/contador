"""Gerador de eventos eSocial em RASCUNHO — corte essencial.

Produz os eventos XML essenciais (S-1000 empregador, S-1010 rubricas,
S-2200 admissão, S-1200 remuneração mensal e S-1299 fechamento) com
tpAmb=2 (produção restrita), empacotados como lista de arquivos para
download em ZIP.

O pacote é um RASCUNHO: sem assinatura digital e com leiaute resumido —
a transmissão oficial exige um evento S-1200 por trabalhador, certificado
ICP-Brasil e as versões de leiaute vigentes. Confira no AVS antes de
qualquer uso. O app não transmite nada.
"""
import io
import zipfile
from collections import defaultdict

NAMESPACE = 'http://www.esocial.gov.br/schema/evt/evtInfoEmpregador/v02_04_02'
VERSAO_PROC = 'AppContabilRascunho'
CLAS_TRIB_VALIDAS = {'01', '08', '30', '40', '99'}


def _esc(texto):
    return (str(texto) if texto is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _cpf_digitos(cpf):
    return ''.join(ch for ch in (cpf or '') if ch.isdigit())


def _data_iso(valor):
    return valor.isoformat() if hasattr(valor, 'isoformat') else str(valor)[:10]


def calcular(folha, rubricas):
    """Totais por empregado e por rubrica, com bases pelas flags de incidência."""
    avisos = []
    rubrica_por_id = {r['id']: r for r in rubricas}
    por_empregado = defaultdict(lambda: dict(proventos=0, descontos=0, base_inss=0, base_irrf=0))
    por_rubrica = defaultdict(lambda: 0)
    for lanc in folha:
        rubrica = rubrica_por_id.get(lanc['rubrica_id'])
        if not rubrica:
            continue
        valor = int(lanc['valor_centavos'])
        linha = por_empregado[lanc['empregado_id']]
        por_rubrica[rubrica['id']] += valor
        if rubrica['tipo'] == 'desconto':
            linha['descontos'] += valor
        else:
            linha['proventos'] += valor
            if rubrica['incid_inss']:
                linha['base_inss'] += valor
            if rubrica['incid_irrf']:
                linha['base_irrf'] += valor
    if not folha:
        avisos.append('Folha vazia para o período: o S-1200 sai sem trabalhadores.')
    return dict(por_empregado=por_empregado, por_rubrica=por_rubrica, avisos=avisos)


def _evento(tag_raiz, idEvento, conteudo):
    """Monta o XML do evento com ideEvento e ideEmpregador comuns."""
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<eSocial xmlns="{NAMESPACE}">'
            f'<{tag_raiz} Id="{idEvento}">{conteudo}</{tag_raiz}>'
            '</eSocial>')


def _ide_evento(periodo_fechamento=False):
    partes = ['<tpAmb>2</tpAmb>', '<procEmi>1</procEmi>', f'<verProc>{VERSAO_PROC}</verProc>']
    if periodo_fechamento:
        return ''.join(partes)
    return ''.join(partes)


def gerar(empresa, parametros, empregados, rubricas, folha, periodo):
    """Monta os eventos essenciais do período e devolve (arquivos, avisos).

    arquivos é uma lista de tuplas (nome_do_arquivo, xml).
    """
    avisos = []
    if not empresa or len(_cpf_digitos(empresa.get('cnpj'))) != 14:
        raise ValueError('Cadastre o CNPJ da empresa antes de gerar o eSocial.')
    cnpj = _cpf_digitos(empresa['cnpj'])
    if not parametros or not (parametros.get('clas_tribut') or '').strip():
        raise ValueError('Parametrize o empregador (classificação tributária) em Fiscal → eSocial antes de gerar o pacote.')

    empregado_por_id = {e['id']: e for e in empregados}
    for lanc in folha:
        if lanc['empregado_id'] not in empregado_por_id:
            avisos.append(f"Lançamento de folha {lanc['id']} com empregado inexistente (ignorado).")
    folha = [l for l in folha if l['empregado_id'] in empregado_por_id]
    numeros = calcular(folha, rubricas)
    avisos.extend(numeros['avisos'])
    for e in empregados:
        if not (e.get('nis') or '').strip():
            avisos.append(f'Empregado "{e["nome"]}" sem NIS/Pasep (S-2200 incompleto).')

    arquivos = []
    corpo_s1000 = ('<ideEvento>' + _ide_evento() + '</ideEvento>'
                   f'<ideEmpregador><tpInsc>1</tpInsc><nrInsc>{cnpj}</nrInsc></ideEmpregador>'
                   '<infoEmpregador>'
                   '<idePeriodo><iniValid>' + periodo + '-01</iniValid><fimValid></fimValid></idePeriodo>'
                   '<infoCadastro>'
                   f'<nmRazao>{_esc((empresa.get("razao_social") or "")[:115])}</nmRazao>'
                   f'<clasTrib>{_esc(parametros.get("clas_tribut"))}</clasTrib>'
                   f'<natJurid>{_esc(parametros.get("nat_juridica"))}</natJurid>'
                   f'<indDeson>{_esc(parametros.get("ind_deson") or "0")}</indDeson>'
                   '</infoCadastro>'
                   '</infoEmpregador>')
    arquivos.append(('S1000_evtInfoEmpregador.xml', _evento('evtInfoEmpregador', 'ID1S1000' + periodo.replace('-', ''), corpo_s1000)))

    corpo_s1010 = ('<ideEvento>' + _ide_evento() + '</ideEvento>'
                   f'<ideEmpregador><tpInsc>1</tpInsc><nrInsc>{cnpj}</nrInsc></ideEmpregador>'
                   '<infoEmpregador><idePeriodo><iniValid>' + periodo + '-01</iniValid><fimValid></fimValid></idePeriodo>')
    for r in rubricas:
        corpo_s1010 += ('<infoRubrica>'
                        f'<ideRubrica><codRubr>{_esc(r["codigo"])}</codRubr><ideTabr>01</ideTabr></ideRubrica>'
                        f'<dadosRubrica><dscRubr>{_esc(r["descricao"])}</dscRubr>'
                        f'<natRubr>4062</natRubr><tpRubr>{1 if r["tipo"] == "provento" else 2}</tpRubr>'
                        '<codIncCP>11</codIncCP><codIncIRRF>11</codIncIRRF><codIncFGTS>11</codIncFGTS>'
                        '</dadosRubrica></infoRubrica>')
    corpo_s1010 += '</infoEmpregador>'
    arquivos.append(('S1010_evtTabRubrica.xml', _evento('evtTabRubrica', 'ID1S1010' + periodo.replace('-', ''), corpo_s1010)))

    for e in empregados:
        cpf = _cpf_digitos(e['cpf'])
        data = _data_iso(e['data_admissao'])
        corpo = ('<ideEvento>' + _ide_evento() + '</ideEvento>'
                 f'<ideEmpregador><tpInsc>1</tpInsc><nrInsc>{cnpj}</nrInsc></ideEmpregador>'
                 '<trabalhador>'
                 f'<cpfTrab>{cpf}</cpfTrab>'
                 f'<nmTrab>{_esc(e["nome"])}</nmTrab>'
                 f'<infoDefici>0</infoDefici>'
                 '</trabalhador>'
                 '<vinculo>'
                 '<infoRegimeTrab><infoCeletista><tpRegTrab>1</tpRegTrab><dtAdm>' + data + '</dtAdm></infoCeletista></infoRegimeTrab>'
                 '<infoContrato>'
                 f'<codCbo>{_esc(e.get("cbo") or "999999")}</codCbo>'
                 f'<vrSalFx>{int(e["salario_centavos"]) / 100:.2f}</vrSalFx><undSalFixo>5</undSalFixo><tpContr>1</tpContr>'
                 '</infoContrato>'
                 '</vinculo>')
        arquivos.append((f'S2200_{cpf}_evtAdmissao.xml', _evento('evtAdmissao', f'ID1S2200{cpf}', corpo)))

    rubrica_por_id = {r['id']: r for r in rubricas}
    por_trabalhador = defaultdict(list)
    for lanc in folha:
        por_trabalhador[lanc['empregado_id']].append(lanc)
    corpo_s1200 = ('<ideEvento>' + _ide_evento(True) + f'<indApuracao>1</indApuracao><perApur>{periodo}</perApur></ideEvento>'
                   f'<ideEmpregador><tpInsc>1</tpInsc><nrInsc>{cnpj}</nrInsc></ideEmpregador>')
    for empregado_id, lancamentos in sorted(por_trabalhador.items()):
        e = empregado_por_id[empregado_id]
        totais = numeros['por_empregado'].get(empregado_id, dict(proventos=0, descontos=0, base_inss=0, base_irrf=0))
        corpo_s1200 += f'<ideTrabalhador><cpfTrab>{_cpf_digitos(e["cpf"])}</cpfTrab><nisTrab>{_esc(e.get("nis"))}</nisTrab></ideTrabalhador>'
        corpo_s1200 += '<dmDev><ideDmDev>DM' + periodo.replace('-', '') + f'{empregado_id}</ideDmDev>'
        for lanc in lancamentos:
            rubrica = rubrica_por_id.get(lanc['rubrica_id'])
            if not rubrica:
                continue
            corpo_s1200 += ('<itensRemun><itemRemun>'
                            f'<codRubr>{_esc(rubrica["codigo"])}</codRubr><ideTabr>01</ideTabr>'
                            f'<vrRubrica>{int(lanc["valor_centavos"]) / 100:.2f}</vrRubrica>'
                            '</itemRemun></itensRemun>')
        corpo_s1200 += '</dmDev>'
    arquivos.append((f'S1200_{periodo}_evtRemun.xml', _evento('evtRemun', f'ID1S1200{periodo.replace("-", "")}', corpo_s1200)))

    total_prov = sum(v['proventos'] for v in numeros['por_empregado'].values())
    total_desc = sum(v['descontos'] for v in numeros['por_empregado'].values())
    corpo_s1299 = ('<ideEvento>' + _ide_evento(True) + f'<perApur>{periodo}</perApur></ideEvento>'
                   f'<ideEmpregador><tpInsc>1</tpInsc><nrInsc>{cnpj}</nrInsc></ideEmpregador>'
                   '<infoFech>'
                   f'<evtRemun>1</evtRemun><evtPgtos>2</evtPgtos><evtAqProd>2</evtAqProd><evtComProd>2</evtComProd>'
                   '<evtComMerc>2</evtComMerc><evtMult>2</evtMult><evtBenefPr>2</evtBenefPr><semCat>0</semCat>'
                   f'<vrTotApur>{(total_prov - total_desc) / 100:.2f}</vrTotApur>'
                   '</infoFech>')
    arquivos.append((f'S1299_{periodo}_evtFechaEvPer.xml', _evento('evtFechaEvPer', f'ID1S1299{periodo.replace("-", "")}', corpo_s1299)))
    return arquivos, avisos


def empacotar(arquivos):
    """Gera o ZIP em memória a partir da lista [(nome, xml)]."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as pacote:
        for nome, conteudo in arquivos:
            pacote.writestr(nome, conteudo)
    return buffer.getvalue()
