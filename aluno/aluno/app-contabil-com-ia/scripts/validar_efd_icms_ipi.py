"""Validador independente da EFD ICMS/IPI rascunho gerada pelo app.

Confere codificação, estrutura de registros, contagens do bloco 9
(9900/9990/9999) e a aritmética interna do E110 (saldo apurado = débitos -
créditos; recolher e saldo credor coerentes). Não substitui o PVA oficial.

Uso: python scripts/validar_efd_icms_ipi.py [caminho_do_arquivo.txt]
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.efd_icms_ipi import gerar, CAMPOS_MINIMOS  # noqa: E402


def _int(valor):
    return int(valor) if valor else 0


def _data_sped(texto):
    return date(int(texto[4:8]), int(texto[2:4]), int(texto[0:2]))


def validar(caminho_arquivo: Path) -> list:
    bruto = caminho_arquivo.read_bytes()
    try:
        texto = bruto.decode('iso-8859-1')
    except UnicodeDecodeError:
        return ['FALHA: arquivo não está em ISO-8859-1 (o PVA espera essa codificação).']
    linhas = texto.splitlines()
    erros = []
    if not linhas or not linhas[0].startswith('|0000|'):
        erros.append('Primeira linha não é o registro de abertura |0000|.')
    if not texto.endswith('\r\n'):
        erros.append('Arquivo não termina com CRLF.')
    for i, l in enumerate(linhas, 1):
        if not (l.startswith('|') and l.endswith('|')):
            erros.append(f'Linha {i}: sem separadores laterais "|" -> {l[:60]}')
            continue
        campos = l[1:].split('|')
        registro = campos[0]
        if registro not in CAMPOS_MINIMOS:
            erros.append(f'Linha {i}: registro não previsto: {registro}.')
        elif len(campos) - 1 < CAMPOS_MINIMOS[registro]:
            erros.append(f'Linha {i}: registro {registro} tem {len(campos)-1} campos (mínimo {CAMPOS_MINIMOS[registro]}).')
    if linhas:
        abertura = linhas[0][1:].split('|')
        try:
            if _data_sped(abertura[4]) < _data_sped(abertura[3]):
                erros.append('Período do 0000: data final anterior à inicial.')
            if abertura[3][4:8] != abertura[4][4:8]:
                erros.append('Período do 0000 não está dentro de um único ano-calendário.')
        except (ValueError, IndexError):
            erros.append('Datas do 0000 ilegíveis (esperado ddmmaaaa).')
    # Contagens declaradas no 9900 × ocorrências reais.
    reais = {}
    for l in linhas:
        registro = l[1:].split('|')[0]
        reais[registro] = reais.get(registro, 0) + 1
    declaradas = {}
    for l in linhas:
        if l.startswith('|9900|'):
            campos = l.strip('|').split('|')
            declaradas[campos[1]] = _int(campos[2])
    for registro, quantidade in declaradas.items():
        if reais.get(registro, 0) != quantidade:
            erros.append(f'9900 declara {quantidade} linhas de {registro}, mas há {reais.get(registro, 0)}.')
    for registro in reais:
        if registro not in declaradas:
            erros.append(f'Registro {registro} presente no arquivo mas ausente do bloco 9900.')
    # 9990 = linhas do bloco 9.
    if '|9001|' in texto and linhas:
        inicio = next(i for i, l in enumerate(linhas) if l.startswith('|9001|'))
        fim_bloco = next((i for i, l in enumerate(linhas) if l.startswith('|9990|')), None)
        if fim_bloco is None:
            erros.append('Bloco 9 sem registro de encerramento 9990.')
        else:
            total_bloco = fim_bloco - inicio + 1
            declarado = _int(linhas[fim_bloco].strip('|').split('|')[1])
            if declarado != total_bloco:
                erros.append(f'9990 declara {declarado} linhas no bloco 9, mas há {total_bloco}.')
    # 9999 = total de linhas.
    if linhas:
        fim = linhas[-1][1:].split('|')
        if fim[0] != '9999':
            erros.append('Última linha não é o encerramento 9999.')
        elif len(fim) > 1 and fim[1].isdigit() and int(fim[1]) != len(linhas):
            erros.append(f'9999 declara {fim[1]} linhas, mas o total correto é {len(linhas)}.')
    # Aritmética do E110: deb(1) - cred(4) = saldo(8); recolher(10) = max(saldo,0); credor(11) = max(-saldo,0).
    e110 = [l for l in linhas if l.startswith('|E110|')]
    if e110:
        c = e110[0].strip('|').split('|')
        deb, cred = _int(c[1]), _int(c[4])
        saldo, recolher, credor = _int(c[8]), _int(c[10]), _int(c[11])
        if saldo != deb - cred:
            erros.append(f'E110: saldo apurado ({saldo}) difere de débitos - créditos ({deb - cred}).')
        if recolher != max(0, saldo):
            erros.append(f'E110: ICMS a recolher ({recolher}) incoerente com o saldo ({saldo}).')
        if credor != max(0, -saldo):
            erros.append(f'E110: saldo credor ({credor}) incoerente com o saldo ({saldo}).')
    # Consolidações C190 × itens do arquivo (somam VL_ICMS por documento).
    tot_c190 = sum(_int(l.strip('|').split('|')[6]) for l in linhas if l.startswith('|C190|'))
    tot_c170 = sum(_int(l.strip('|').split('|')[14]) for l in linhas if l.startswith('|C170|'))
    if tot_c190 != tot_c170:
        erros.append(f'C190 consolida {tot_c190} de ICMS, mas os C170 somam {tot_c170}.')
    return erros


def main():
    if len(sys.argv) > 1:
        alvo = Path(sys.argv[1])
    else:
        raise SystemExit('Informe o caminho do arquivo: python scripts/validar_efd_icms_ipi.py arquivo.txt')
    erros = validar(alvo)
    if erros:
        print(f'FALHAS ({len(erros)}):')
        for e in erros:
            print(' -', e)
        return 1
    print(f'OK: {alvo.name} passou em todas as verificações estruturais.')
    print('Lembrete: a validação oficial final é no PVA da Receita (Windows).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
