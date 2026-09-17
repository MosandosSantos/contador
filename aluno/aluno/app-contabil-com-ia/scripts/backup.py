"""Backup dos dados do banco local do app em arquivo SQL restaurável.

Uso: python scripts/backup.py [PASTA_DESTINO]
Sem argumento, grava em backups/ dentro da pasta do app.
O esquema não é exportado: ele é recriado por scripts/schema.sql na restauração.
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.local import read_json, SECRETS_FILE, RUNTIME  # noqa: E402
import psycopg2  # noqa: E402

SCHEMA = 'public'


def _conexao():
    segredos = read_json(SECRETS_FILE)
    if not segredos.get('database_password'):
        raise SystemExit('Sem segredos locais: inicie o app uma vez antes de fazer backup.')
    estado = read_json(RUNTIME / 'estado.json')
    porta = int(estado.get('postgres_port') or segredos.get('database_port') or 5433)
    # Mesmo formato de DSN usado pelo aplicativo (URL), caminho de conexão já provado.
    dsn = f"postgresql://app_contabil:{segredos['database_password']}@127.0.0.1:{porta}/app_contabil"
    return psycopg2.connect(dsn, connect_timeout=5)


def _tabelas(cur):
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name", (SCHEMA,))
    return [r[0] for r in cur.fetchall()]


def _colunas(cur, tabela):
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (SCHEMA, tabela))
    return [r[0] for r in cur.fetchall()]


def _coluna_serial(cur, tabela):
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s AND column_default LIKE '%%nextval%%' "
                "ORDER BY ordinal_position LIMIT 1", (SCHEMA, tabela))
    r = cur.fetchone()
    return r[0] if r else None


def main():
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'backups'
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / f'app_contabil_{datetime.now():%Y%m%d_%H%M%S}.sql'
    conn = _conexao()
    total = 0
    with conn:
        with conn.cursor() as cur:
            tabelas = _tabelas(cur)
            with open(alvo, 'w', encoding='utf-8', newline='\n') as arq:
                arq.write(f'-- QuantIA · backup de dados {datetime.now():%Y-%m-%d %H:%M:%S}\n')
                arq.write('-- Restaurar em banco com o esquema já criado (scripts/schema.sql).\n')
                arq.write('BEGIN;\n')
                for t in tabelas:
                    arq.write(f'TRUNCATE TABLE {SCHEMA}.{t} CASCADE;\n')
                arq.write('COMMIT;\n')
                for t in tabelas:
                    colunas = _colunas(cur, t)
                    if not colunas:
                        continue
                    lista = ', '.join(colunas)
                    arq.write(f'\n-- tabela {t}\n')
                    arq.write(f'COPY {SCHEMA}.{t} ({lista}) FROM stdin;\n')
                    cur.copy_expert(f'COPY {SCHEMA}.{t} ({lista}) TO STDOUT', arq)
                    arq.write('\\.\n')
                    total += 1
                # Sequências (id serial) precisam ser realinhadas após o COPY.
                for t in tabelas:
                    col = _coluna_serial(cur, t)
                    if col:
                        arq.write(f"SELECT setval(pg_get_serial_sequence('{SCHEMA}.{t}','{col}'), "
                                  f"COALESCE((SELECT MAX({col}) FROM {SCHEMA}.{t}), 0) + 1, false);\n")
    conn.close()
    print(f'Backup concluído: {alvo} ({total} tabelas).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
