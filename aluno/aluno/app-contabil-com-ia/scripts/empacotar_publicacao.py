#!/usr/bin/env python3
"""
Auto-empacota o app para publicar no EasyPanel.

Roda de dentro da pasta do app (chamado por publicar.bat). Gera um ZIP enxuto
com Dockerfile na raiz ouvindo na porta 5000, SEM banco local, chaves, runtime
nem logs. No fim, mostra exatamente o que colar no Ambiente do EasyPanel
(DATABASE_URL + SECRET_KEY) e já sugere uma SECRET_KEY aleatoria.
"""
from __future__ import annotations

import secrets
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent      # <app>/scripts
APP = AQUI.parent                            # <app>

DOCKERFILE = """FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production PORT=5000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY app.py .
COPY config/ config/
COPY core/ core/
COPY modules/ modules/
COPY templates/ templates/
COPY static/ static/
COPY dados/ dados/
COPY scripts/schema.sql scripts/schema.sql
COPY scripts/preparar.py scripts/preparar.py
USER appuser
EXPOSE 5000
CMD ["sh", "-c", "python scripts/preparar.py && exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 2 --timeout 60 app:app"]
"""

DOCKERIGNORE = """.env
.runtime/
.venv/
__pycache__/
*.pyc
*.log
*.zip
*.dump
"""

EXCLUIR_DIRS = {".runtime", ".venv", "__pycache__", ".git", "z_Versoes"}
EXCLUIR_SUFIXOS = (".pyc", ".log", ".zip", ".dump")
EXCLUIR_ARQUIVOS = {".env", "Dockerfile", ".dockerignore"}


def incluir(rel: Path) -> bool:
    if any(parte in EXCLUIR_DIRS for parte in rel.parts):
        return False
    if rel.suffix.lower() in EXCLUIR_SUFIXOS:
        return False
    if rel.name in EXCLUIR_ARQUIVOS or rel.as_posix() in EXCLUIR_ARQUIVOS:
        return False
    if rel.name.startswith("segredos"):
        return False
    return True


def main() -> int:
    saida = APP.parent / f"{APP.name}_SubirEasyPanel.zip"
    if saida.exists():
        saida.unlink()
    arquivos = [p for p in APP.rglob("*") if p.is_file() and incluir(p.relative_to(APP))]
    with zipfile.ZipFile(saida, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in arquivos:
            z.writestr(p.relative_to(APP).as_posix(), p.read_bytes())
        z.writestr("Dockerfile", DOCKERFILE)
        z.writestr(".dockerignore", DOCKERIGNORE)

    chave = secrets.token_hex(32)
    print("=" * 60)
    print("  PRONTO PARA PUBLICAR")
    print("  Arquivo gerado: " + str(saida))
    print("=" * 60)
    print("")
    print("No EasyPanel:")
    print(" 1) Servico App -> Fonte: Upload -> suba este ZIP -> Build: Dockerfile.")
    print(" 2) Servico PostgreSQL -> copie a URL interna de conexao.")
    print(" 3) No App, aba Ambiente, defina SOMENTE estas duas variaveis:")
    print("")
    print("    DATABASE_URL=postgresql://USUARIO:SENHA@HOST_INTERNO:5432/BANCO")
    print("    SECRET_KEY=" + chave)
    print("")
    print(" 4) No App, aba Dominio: aponte para a porta 5000 e ative HTTPS. Implante.")
    print("")
    print("(A SECRET_KEY acima foi gerada aleatoria agora; pode usar essa mesma.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
