#!/usr/bin/env python3
"""
Atualizador a prova de leigo.

Roda de DENTRO da pasta do aplicativo (chamado por atualizar.bat). Reconhece a
propria pasta, abre um seletor para a pessoa escolher o ZIP da nova versao que
baixou, e aplica a atualizacao pela ponte testada (progressao.atualizar):
preserva banco, .runtime, config/app.json, chave e anexos, com deteccao de
conflito e reversao automatica. Nao precisa do plugin instalado no Windows,
nao precisa extrair o ZIP na mao e nao precisa digitar nenhum caminho.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

AQUI = Path(__file__).resolve().parent      # <app>/scripts
APP = AQUI.parent                            # <app>  (a propria pasta do app)
sys.path.insert(0, str(AQUI))
import progressao  # a ponte de atualizacao ja viaja dentro do proprio app

MARCADOR = '.app-contabil-template.json'


def _raiz_no_zip(pasta: Path) -> Path:
    """Acha a pasta do app dentro do ZIP extraido (onde esta o marcador)."""
    if (pasta / MARCADOR).is_file():
        return pasta
    for encontrado in pasta.rglob(MARCADOR):
        if encontrado.is_file():
            return encontrado.parent
    raise ValueError('O arquivo escolhido nao parece ser uma versao deste aplicativo.')


def _escolher_zip() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001
        raise ValueError('Nao consegui abrir a janela de selecao. Rode: python scripts/atualizar_selecionar.py --zip "CAMINHO DO ZIP".') from exc
    janela = tk.Tk()
    janela.withdraw()
    janela.attributes('-topmost', True)
    caminho = filedialog.askopenfilename(
        title='Escolha o ZIP da nova versao do app (o que voce acabou de baixar)',
        filetypes=[('Arquivo ZIP', '*.zip'), ('Todos os arquivos', '*.*')],
    )
    janela.destroy()
    return caminho


def main() -> int:
    parser = argparse.ArgumentParser(description='Atualiza este app com o ZIP de uma nova versao.')
    parser.add_argument('--zip', help='Caminho do ZIP da nova versao. Se omitido, abre o seletor.')
    args = parser.parse_args()

    print('=' * 56)
    print('  ATUALIZAR O APP')
    print('  Pasta deste app: ' + str(APP))
    print('=' * 56)

    escolhido = args.zip or _escolher_zip()
    if not escolhido:
        print('\nNenhum arquivo escolhido. Nada foi alterado.')
        return 1
    zip_novo = Path(escolhido).expanduser().resolve()
    if not zip_novo.is_file() or not zipfile.is_zipfile(zip_novo):
        print('\nO arquivo escolhido nao e um ZIP valido. Nada foi alterado.')
        return 1

    print('\nNova versao: ' + zip_novo.name)
    print('Aplicando... (seus dados, configuracao e chave sao preservados)')
    try:
        with tempfile.TemporaryDirectory(prefix='.nova-versao-') as tmp:
            with zipfile.ZipFile(zip_novo) as pacote:
                pacote.extractall(tmp)
            origem = _raiz_no_zip(Path(tmp))
            resultado = progressao.atualizar(origem, APP)
    except ValueError as erro:
        print('\nNAO foi possivel atualizar: ' + str(erro))
        if 'execu' in str(erro).lower():
            print('Feche o app primeiro: de dois cliques em parar.bat, depois rode este atualizador de novo.')
        else:
            print('Nada foi alterado. Volte ao chat com essa mensagem para revisar.')
        return 1
    except OSError as erro:
        print('\nErro de arquivo: ' + str(erro) + '\nNada foi alterado.')
        return 1

    novos = [m for m in resultado.get('atualizado', []) ]
    print('\nPRONTO! App atualizado.')
    print('Etapas agora disponiveis: ' + ', '.join(novos))
    print('Abra iniciar.bat para usar. Seus dados anteriores continuam la.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
