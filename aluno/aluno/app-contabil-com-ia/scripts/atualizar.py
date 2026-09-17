#!/usr/bin/env python3
"""Ponte autocontida: aplica o ZIP extraído à pasta original parada."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import webbrowser
from pathlib import Path
from progressao import atualizar

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--origem', default=str(Path(__file__).resolve().parents[1]))
    p.add_argument('--destino')
    p.add_argument('--iniciar', action='store_true')
    p.add_argument('--sem-navegador', action='store_true', help='Inicia a instância sem abrir uma aba (ensaio automatizado).')
    a = p.parse_args()
    try:
        destino = Path(a.destino or input('Pasta ORIGINAL do app (depois de executar parar.bat): ').strip().strip('"')).expanduser().resolve()
        if not destino.is_dir():
            raise ValueError('Pasta original não encontrada.')
        resultado = atualizar(Path(a.origem).resolve(), destino)
        print(json.dumps(resultado, ensure_ascii=False))
    except (OSError, ValueError) as e:
        print(f'Atualização não realizada: {e}')
        return 1
    if a.iniciar:
        r = subprocess.run([sys.executable, str(destino / 'scripts/local.py'), '--start'], cwd=destino)
        if r.returncode:
            print('Atualização aplicada. A inicialização falhou; execute iniciar.bat na pasta ORIGINAL para ver o diagnóstico.')
            return r.returncode
        s = json.loads((destino / '.runtime/estado.json').read_text(encoding='utf-8'))
        if not a.sem_navegador and str(s.get('url', '')).startswith('http://127.0.0.1:'):
            webbrowser.open(s['url'])
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
