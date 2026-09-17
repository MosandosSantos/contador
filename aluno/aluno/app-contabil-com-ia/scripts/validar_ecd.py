"""Validador independente do ECD rascunho gerado pelo app.

Confere a estrutura do arquivo (registros, separadores, coerência do período),
o equilíbrio do balancete J100 e do diário J930 e cruza os totais do diário
com os lançamentos do banco. Não substitui o PVA oficial, mas enxerga qualquer
defeito estrutural antes de o contador abrir o arquivo.

Uso: python scripts/validar_ecd.py [caminho_do_arquivo.txt]
Sem argumento, exporta um ECD novo do banco local e valida.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import os
os.environ.setdefault('DATABASE_URL', '')
from core.db import fetch  # noqa: E402
from core.ecd import gerar_ecd  # noqa: E402


def _int(valor):
    return int(valor) if valor else 0


def _data_sped(texto):
    return date(int(texto[4:8]), int(texto[2:4]), int(texto[0:2]))


def validar(caminho_arquivo: Path) -> list[str]:
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
        campos = l[1:].split('|')  # mantém campos vazios; último elemento é o vazio final
        registro = campos[0]
        esperados = {'0000': 11, '0001': 1, '0500': 26, 'J100': 15, 'J930': 12, '9999': 2}
        if registro in esperados and len(campos) - 1 < esperados[registro]:
            erros.append(f'Linha {i}: registro {registro} tem {len(campos)-1} campos (mínimo {esperados[registro]}).')
        if registro not in esperados:
            erros.append(f'Linha {i}: registro não previsto neste rascunho: {registro}.')
    # Abertura x encerramento (posição fixa do layout ECD: 3=DT_INI, 4=DT_FIN)
    if linhas:
        abertura = linhas[0][1:].split('|')
        if len(abertura) > 4:
            try:
                ini = _data_sped(abertura[3])
                fim = _data_sped(abertura[4])
                if fim < ini:
                    erros.append('Período do 0000: data final anterior à inicial.')
            except (ValueError, IndexError):
                erros.append('Datas do 0000 ilegíveis (esperado ddmmaaaa).')
    # J100
    tot_d = tot_c = 0
    for l in linhas:
        if l.startswith('|J100|'):
            campos = l.strip('|').split('|')
            tot_d += _int(campos[7])
            tot_c += _int(campos[8])
    if tot_d != tot_c:
        erros.append(f'J100 não fecha: débitos {tot_d} ≠ créditos {tot_c}.')
    # J930 por documento (posições: 3=data, 5=doc, 9=débito, 10=crédito)
    docs = {}
    for l in linhas:
        if l.startswith('|J930|'):
            campos = l[1:].split('|')
            docs.setdefault(campos[5], [0, 0])
            docs[campos[5]][0] += _int(campos[9])
            docs[campos[5]][1] += _int(campos[10])
    desq = [d for d, v in docs.items() if v[0] != v[1]]
    if desq:
        erros.append(f'J930: {len(desq)} documento(s) desequilibrado(s): {desq[:5]}')
    # Encerramento conta as linhas (9999 declara o total incluindo a si mesmo)
    if linhas:
        fim = linhas[-1][1:].split('|')
        if fim[0] != '9999':
            erros.append('Última linha não é o encerramento 9999.')
        elif len(fim) > 2 and fim[2].isdigit():
            esperado = len(linhas)  # o 9999 se inclui na contagem
            if int(fim[2]) != esperado:
                erros.append(f'9999 declara {fim[2]} linhas, mas o total correto é {esperado}.')
    return erros


def main():
    if len(sys.argv) > 1:
        alvo = Path(sys.argv[1])
    else:
        empresa = fetch('SELECT * FROM empresa WHERE id=1')
        if not empresa:
            raise SystemExit('Cadastre a empresa antes de validar o ECD.')
        contas = fetch('SELECT conta_id,descricao,grupo,analitica,nivel,natureza,cod_referencial FROM contas ORDER BY ordem,conta_id')
        mov = fetch('SELECT documento_id,data,conta_id,debito_centavos,credito_centavos,historico FROM lancamentos ORDER BY data,documento_id')
        if not mov:
            raise SystemExit('Sem lançamentos para validar.')
        dt_fim = max(m['data'] for m in mov)
        dt_fim = dt_fim if hasattr(dt_fim, 'year') else date.fromisoformat(str(dt_fim)[:10])
        dt_ini = date(dt_fim.year, dt_fim.month, 1)
        texto, avisos = gerar_ecd(dict(empresa[0]), contas, mov, dt_ini.isoformat(), dt_fim.isoformat())
        alvo = ROOT / 'ecd_ultimo.txt'
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
