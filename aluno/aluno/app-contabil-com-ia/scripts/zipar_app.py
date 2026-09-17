#!/usr/bin/env python3
"""Compacta a lista de fontes progressivas; nunca inclui runtime/banco/chaves."""
from __future__ import annotations
import argparse
import json
import zipfile
from pathlib import Path, PurePosixPath
from progressao import estado, caminho, sha256, json_bytes, MARCADOR, ESTADO

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--app', required=True)
    p.add_argument('--saida', required=True)
    a = p.parse_args()
    app, saida = Path(a.app).resolve(), Path(a.saida).resolve()
    try:
        registro = estado(app)
        if saida.exists() or not saida.parent.is_dir():
            raise ValueError('Informe um ZIP novo em pasta existente.')
        arquivos = {}
        for n, esperado in registro['arquivos'].items():
            arquivo = caminho(app, n)
            if not arquivo.is_file():
                raise ValueError('Arquivo obrigatório ausente: ' + n)
            b = arquivo.read_bytes()
            if n != 'config/app.json' and sha256(b) != esperado:
                raise ValueError('Fonte personalizada diverge do manifesto; revise antes de distribuir: ' + n)
            arquivos[n] = b
        registro['arquivos']['config/app.json'] = sha256(arquivos['config/app.json'])
        arquivos[ESTADO] = json_bytes(registro)
        arquivos[MARCADOR] = caminho(app, MARCADOR).read_bytes()
        # Toda validação termina antes de criar a saída.
        with zipfile.ZipFile(saida, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for n, b in sorted(arquivos.items()):
                z.writestr(PurePosixPath(app.name, n).as_posix(), b)
    except (OSError, ValueError) as e:
        print(f'Compactação não realizada: {e}')
        return 1
    print(json.dumps({'arquivo': str(saida), 'sha256': sha256(saida.read_bytes()), 'arquivos': len(arquivos)}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
