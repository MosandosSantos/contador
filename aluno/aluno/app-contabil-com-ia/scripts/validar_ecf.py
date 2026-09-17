"""Validador independente da ECF rascunho gerada pelo app.

Confere codificação, estrutura de registros, contagens do 9999, equilíbrio do
balancete J030 e coerência M300/M310. Não substitui o PVA oficial.

Uso: python scripts/validar_ecf.py [caminho_do_arquivo.txt]
Sem argumento, gera uma ECF do banco local (se possível) e valida.
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ecf import gerar_ecf, CAMPOS_MINIMOS  # noqa: E402


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
    mov_d = mov_c = 0
    for l in linhas:
        if l.startswith('|J030|'):
            campos = l.strip('|').split('|')
            mov_d += _int(campos[8])
            mov_c += _int(campos[9])
    if mov_d != mov_c:
        erros.append(f'J030 não fecha: débitos {mov_d} ≠ créditos {mov_c}.')
    m300 = {}
    for l in linhas:
        if l.startswith('|M300|'):
            campos = l.strip('|').split('|')
            m300[campos[1]] = _int(campos[2])
    m310 = {}
    periodo_atual = None
    for l in linhas:
        if l.startswith('|M300|'):
            campos = l.strip('|').split('|')
            periodo_atual = campos[1]
            m310.setdefault(periodo_atual, 0)
        elif l.startswith('|M310|') and periodo_atual:
            m310[periodo_atual] += 1
    for periodo, quantidade in m300.items():
        if m310.get(periodo, 0) != quantidade:
            erros.append(f'M300 {periodo} declara {quantidade} lançamentos, mas há {m310.get(periodo, 0)} linhas M310.')
    if linhas:
        fim = linhas[-1][1:].split('|')
        if fim[0] != '9999':
            erros.append('Última linha não é o encerramento 9999.')
        elif len(fim) > 2 and fim[2].isdigit() and int(fim[2]) != len(linhas):
            erros.append(f'9999 declara {fim[2]} linhas, mas o total correto é {len(linhas)}.')
    return erros


def main():
    if len(sys.argv) > 1:
        alvo = Path(sys.argv[1])
    else:
        try:
            from core.db import fetch
        except Exception:
            raise SystemExit('Informe o caminho do arquivo: python scripts/validar_ecf.py arquivo.txt')
        empresa = fetch('SELECT * FROM empresa WHERE id=1')
        if not empresa:
            raise SystemExit('Cadastre a empresa antes de validar o ECF.')
        ano = max((m['data'].year for m in fetch('SELECT data FROM lancamentos')), default=date.today().year)
        parametros = next((x for x in fetch('SELECT * FROM ecf_parametros WHERE ano=%s', (ano,))), None)
        texto, avisos = gerar_ecf(dict(empresa[0]),
                                  fetch('SELECT conta_id,descricao,grupo,analitica,nivel,cod_referencial,linha_dre FROM contas ORDER BY ordem,conta_id'),
                                  fetch('SELECT data,conta_id,debito_centavos,credito_centavos,tipo FROM lancamentos ORDER BY data'),
                                  fetch('SELECT documento,nome FROM participantes ORDER BY nome'),
                                  parametros, fetch('SELECT * FROM ecf_contas_pb ORDER BY codigo'),
                                  fetch('SELECT * FROM ecf_lancamentos WHERE periodo LIKE %s ORDER BY periodo,data,id', (f'{ano}%',)),
                                  fetch('SELECT * FROM ecf_conciliacao ORDER BY ordem,id'), ano)
        alvo = ROOT / 'ecf_ultimo.txt'
        alvo.write_bytes(texto.encode('iso-8859-1'))
        for a in avisos:
            print('Aviso do gerador:', a)
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
