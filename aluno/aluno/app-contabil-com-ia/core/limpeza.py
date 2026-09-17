"""Limpeza atômica da base de negócio, preservando acesso e migrações."""
from core.db import connection

PROTEGIDAS = {"usuarios", "login_tentativas", "versoes_schema", "configuracoes_ia"}


def limpar_dados_negocio():
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(20260911)')
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        tables = sorted({row[0] for row in cur.fetchall()} - PROTEGIDAS)
        if tables:
            nomes = ', '.join('"' + table.replace('"', '""') + '"' for table in tables)
            cur.execute('TRUNCATE TABLE ' + nomes + ' RESTART IDENTITY')
    return len(tables)
