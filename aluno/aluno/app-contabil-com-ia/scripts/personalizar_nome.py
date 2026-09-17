#!/usr/bin/env python3
"""Troca somente o nome exibido em um app montado por este plugin."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MARCADOR = ".app-contabil-template.json"
ARQUIVOS = ()  # O nome é configuração; fonte gerenciada continua idêntica ao manifesto.
CONFIGURACAO = "config/app.json"


def nome_valido(valor: str) -> str:
    nome = " ".join(valor.split())
    if not 3 <= len(nome) <= 60 or any(ord(caractere) < 32 for caractere in nome):
        raise ValueError("O nome do app deve ter entre 3 e 60 caracteres visíveis.")
    return nome


def trocar_nome(app: Path, nome: str) -> None:
    nome = nome_valido(nome)
    marcador = app / MARCADOR
    if not marcador.is_file():
        raise ValueError("A pasta não parece ter sido montada por este plugin; o nome não foi alterado.")
    estado = json.loads(marcador.read_text(encoding="utf-8"))
    anterior = estado.get("nome_app")
    if not isinstance(anterior, str) or not anterior:
        raise ValueError("O marcador do template não contém o nome atual.")
    configuracao = app / CONFIGURACAO
    if not configuracao.is_file():
        raise ValueError(f"Arquivo de configuração ausente: {CONFIGURACAO}.")
    dados = json.loads(configuracao.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise ValueError("A configuração de apresentação não contém um objeto JSON.")
    dados["nome_app"] = nome
    configuracao.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for relativo in ARQUIVOS:
        caminho = app / relativo
        if not caminho.is_file():
            raise ValueError(f"Arquivo de personalização ausente: {relativo}.")
        texto = caminho.read_text(encoding="utf-8")
        caminho.write_text(texto.replace(anterior, nome), encoding="utf-8")
    estado["nome_app"] = nome
    marcador.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Altera o nome visível de um app montado.")
    parser.add_argument("--app", required=True, help="Pasta já montada pelo plugin.")
    parser.add_argument("--nome-app", required=True, help="Novo nome visível do app.")
    args = parser.parse_args()
    try:
        app = Path(args.app).expanduser().resolve()
        if not app.is_dir():
            raise ValueError("A pasta do app não existe.")
        trocar_nome(app, nome_valido(args.nome_app))
    except (OSError, ValueError, json.JSONDecodeError) as erro:
        print(f"Personalização não realizada: {erro}")
        return 1
    print(f"Nome atualizado em: {app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
