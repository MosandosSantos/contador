#!/usr/bin/env python3
"""Regenera config/modulos.json: reconta os hashes dos arquivos e acrescenta novos.

Mantém schema, projeto_id, habilitados e template_sha256. Novos arquivos entram
somente se forem caminhos permitidos pelo template (permitido() de progressao.py).
docs/superpowers (planos internos de sessão) ficam fora do manifesto.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path, PurePosixPath

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / 'scripts'))
from progressao import permitido, caminho, sha256, json_bytes, estado, ESTADO, MARCADOR  # noqa: E402

EXCLUIR_PREFIXOS = ('docs/superpowers/', ESTADO, MARCADOR)


def main() -> int:
    manifesto_path = APP / ESTADO
    dados = json.loads(manifesto_path.read_text(encoding='utf-8'))
    atuais = {n: h for n, h in dados['arquivos'].items()
              if not any(n.startswith(prefixo) or n == prefixo for prefixo in EXCLUIR_PREFIXOS)}
    # 1) Recontar os que já estão no manifesto (removidos saem).
    arquivos = {}
    for nome in atuais:
        p = caminho(APP, nome)
        if not p.is_file():
            print('removido do manifesto (arquivo sumiu):', nome)
            continue
        arquivos[nome] = sha256(p.read_bytes())
    # 2) Acrescentar novos arquivos permitidos do app.
    novos = []
    for p in sorted(APP.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(APP).as_posix()
        if any(rel.startswith(prefixo) for prefixo in EXCLUIR_PREFIXOS):
            continue
        if rel in arquivos or '__pycache__' in rel or rel.startswith('.runtime/'):
            continue
        if permitido(rel):
            arquivos[rel] = sha256(p.read_bytes())
            novos.append(rel)
    dados['arquivos'] = dict(sorted(arquivos.items()))
    # 3) Validar com as regras do runtime antes de gravar.
    manifesto_path.write_bytes(json_bytes(dados))
    estado(APP)
    print(f'manifesto regenerado: {len(dados["arquivos"])} arquivos, {len(novos)} novo(s)')
    for n in novos:
        print('  +', n)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
