"""Validador independente do pacote eSocial rascunho gerado pelo app.

Abre o ZIP, confere os membros esperados, parseia cada XML (evento correto,
CNPJ do empregador, CPFs válidos dos trabalhadores) e cruza os totais do
S-1200 com o S-1299. Não substitui o AVS oficial.

Uso: python scripts/validar_esocial.py [caminho_do_pacote.zip]
"""
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = '{http://www.esocial.gov.br/schema/evt/evtInfoEmpregador/v02_04_02}'
EVENTOS_ESPERADOS = ('evtInfoEmpregador', 'evtTabRubrica', 'evtRemun', 'evtFechaEvPer')


def _cpf_valido(valor):
    d = re.sub(r'\D', '', valor or '')
    if len(d) != 11 or d == d[0] * 11:
        return False
    def dv(chave, pesos):
        soma = sum(int(x) * p for x, p in zip(chave, pesos))
        r = (soma * 10) % 11
        return r % 10
    return dv(d[:9], range(10, 1, -1)) == int(d[9]) and dv(d[:10], range(11, 1, -1)) == int(d[10])


def validar(caminho_arquivo: Path) -> list:
    erros = []
    try:
        pacote = zipfile.ZipFile(caminho_arquivo)
    except zipfile.BadZipFile:
        return ['FALHA: o arquivo não é um ZIP válido.']
    nomes = pacote.namelist()
    if not any('S1000' in n for n in nomes):
        erros.append('Falta o S-1000 (empregador).')
    if not any('S1010' in n for n in nomes):
        erros.append('Falta o S-1010 (rubricas).')
    if not any('S1200' in n for n in nomes):
        erros.append('Falta o S-1200 (remuneração).')
    if not any('S1299' in n for n in nomes):
        erros.append('Falta o S-1299 (fechamento).')
    cnpj_empregador = None
    for nome in nomes:
        raiz = ET.fromstring(pacote.read(nome))
        evento = raiz[0]
        tag = evento.tag.replace(NS, '')
        if tag not in EVENTOS_ESPERADOS and not tag.startswith('evtAdmissao'):
            erros.append(f'{nome}: evento inesperado "{tag}".')
        ide = evento.find(f'{NS}ideEmpregador')
        if ide is None:
            erros.append(f'{nome}: sem ideEmpregador.')
            continue
        nr = ide.findtext(f'{NS}nrInsc', '')
        if cnpj_empregador is None:
            cnpj_empregador = nr
        elif nr != cnpj_empregador:
            erros.append(f'{nome}: CNPJ do empregador difere dos demais eventos.')
        if tag.startswith('evtAdmissao'):
            cpf = evento.findtext(f'{NS}trabalhador/{NS}cpfTrab', '')
            if not _cpf_valido(cpf):
                erros.append(f'{nome}: CPF do trabalhador inválido ({cpf}).')
    totais_s1200 = 0.0
    for nome in [n for n in nomes if 'S1200' in n]:
        raiz = ET.fromstring(pacote.read(nome))
        totais_s1200 += sum(float(x.text or 0) for x in raiz.iter(f'{NS}vrRubrica'))
    s1299 = [n for n in nomes if 'S1299' in n]
    if s1299:
        raiz = ET.fromstring(pacote.read(s1299[0]))
        fechado = float(raiz.findtext(f'.//{NS}vrTotApur', '0'))
        if abs(fechado - totais_s1200) > 0.01:
            erros.append(f'S-1299 fecha {fechado}, mas os itens do S-1200 somam {totais_s1200:.2f}.')
    return erros


def main():
    if len(sys.argv) > 1:
        alvo = Path(sys.argv[1])
    else:
        raise SystemExit('Informe o caminho: python scripts/validar_esocial.py esocial_rascunho.zip')
    erros = validar(alvo)
    if erros:
        print(f'FALHAS ({len(erros)}):')
        for e in erros:
            print(' -', e)
        return 1
    print(f'OK: {alvo.name} passou em todas as verificações estruturais.')
    print('Lembrete: a conferência final é no validador oficial (AVS), com assinatura para transmissão.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
