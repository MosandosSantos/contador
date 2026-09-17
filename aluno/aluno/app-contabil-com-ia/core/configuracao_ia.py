"""Configuração técnica da instância. O segredo nunca compõe o contexto da tela."""
import os
import re
from core.db import fetch, connection

from core.modelos_ia import MODELO_PADRAO


def efetiva():
    rows = fetch('SELECT chave,modelo,atualizado FROM configuracoes_ia WHERE id=1')
    if rows:
        row = rows[0]
        return {'chave': row['chave'], 'modelo': row['modelo'],
                'origem': 'aplicativo', 'revisao': row['atualizado'].isoformat()}
    return {'chave': os.environ.get('NVIDIA_API_KEY', '').strip(),
            'modelo': os.environ.get('NVIDIA_MODEL', '').strip() or MODELO_PADRAO,
            'origem': 'ambiente', 'revisao': 'ambiente'}


def candidata(chave, modelo):
    if not isinstance(chave, str) or not isinstance(modelo, str):
        raise ValueError('Informe a chave e selecione um modelo.')
    chave, modelo = chave.strip(), modelo.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{1,119}', modelo):
        raise ValueError('Selecione um modelo antes de testar a conexão.')
    if chave and (not chave.startswith('nvapi-') or not 20 <= len(chave) <= 500
                  or not re.fullmatch(r'[A-Za-z0-9_-]+', chave)):
        raise ValueError('A chave deve começar com nvapi-. Copie a chave completa do NVIDIA Build.')
    chave = chave or efetiva()['chave']
    if not chave:
        raise ValueError('Informe sua chave NVIDIA antes de testar a conexão.')
    return {'chave': chave, 'modelo': modelo}


def salvar(chave, modelo):
    cfg = candidata(chave, modelo)
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(20260914)')
        cur.execute('''INSERT INTO configuracoes_ia(id,chave,modelo) VALUES(1,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET chave=EXCLUDED.chave,
                       modelo=EXCLUDED.modelo,atualizado=clock_timestamp()''', (cfg['chave'], cfg['modelo']))
