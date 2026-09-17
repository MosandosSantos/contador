import csv
import io
import re
from collections import defaultdict
from datetime import date
from psycopg2.extras import RealDictCursor, Json
from core.db import connection

CAMPOS=['linha_id','documento_id','empresa_id','data','conta_id','debito_centavos','credito_centavos','tipo','historico','origem_id','centro_id','atividade_caixa','rubrica_caixa']
TIPOS={'abertura','receita','recebimento','pagamento','competencia','depreciacao','aporte','distribuicao','encerramento','reserva','investimento'}

def ler_csv(raw):
    try: text=raw.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('Use CSV UTF-8.')
    reader=csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames): raise ValueError('Cabeçalho inválido ou repetido.')
    rows=list(reader)
    if not rows or len(rows)>5000: raise ValueError('Envie de 1 a 5.000 linhas por arquivo.')
    if any(None in row or any(v is None for v in row.values()) for row in rows): raise ValueError('CSV com quantidade de colunas inconsistente.')
    return rows

def validar_lancamentos(rows, contas):
    ids=set();docs=defaultdict(list)
    for row in rows:
        if set(row)!=set(CAMPOS): raise ValueError('Colunas diferentes do modelo. Baixe o CSV de exemplo.')
        if row['linha_id'] in ids: raise ValueError('Identificador de linha duplicado no arquivo.')
        ids.add(row['linha_id'])
        if any(len(str(v))>300 for v in row.values()): raise ValueError('Campo maior que 300 caracteres.')
        if not row['linha_id'] or not row['documento_id']: raise ValueError('Informe identificadores de linha e documento.')
        if row['conta_id'] not in contas: raise ValueError('Conta não mapeada: '+row['conta_id'])
        try: data_lancamento = date.fromisoformat(row['data'])
        except (TypeError, ValueError): raise ValueError('Data inválida.')
        if not 1900 <= data_lancamento.year <= 2199: raise ValueError('Ano fora de 1900–2199.')
        if row['empresa_id']!='EMPRESA_WORKSHOP_01': raise ValueError('Empresa diferente do caso fictício.')
        if row['tipo'] not in TIPOS: raise ValueError('Tipo de documento inválido.')
        for k in ('debito_centavos','credito_centavos'):
            if not re.fullmatch(r'\d{1,12}',str(row[k])): raise ValueError('Valor monetário deve ser inteiro não negativo, em centavos.')
            row[k]=int(row[k])
        if row['debito_centavos'] and row['credito_centavos']: raise ValueError('Uma linha não pode ter débito e crédito juntos.')
        if not row['debito_centavos'] and not row['credito_centavos']: raise ValueError('Linha sem débito nem crédito não é um lançamento.')
        if row['conta_id']=='1.1.1' and row['tipo']!='abertura' and row['atividade_caixa'] not in ('operacional','investimento','financiamento'):
            raise ValueError('Movimento bancário sem atividade da DFC.')
        docs[row['documento_id']].append(row)
    for doc,lines in docs.items():
        if len({(x['data'],x['tipo']) for x in lines})!=1: raise ValueError('Documento com datas ou tipos diferentes: '+doc)
        if sum(x['debito_centavos']-x['credito_centavos'] for x in lines)!=0: raise ValueError('Documento desbalanceado: '+doc)
    return rows

def importar(rows):
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT pg_advisory_xact_lock(20260911)')
        cur.execute('SELECT conta_id FROM contas');contas={x['conta_id'] for x in cur.fetchall()}
        validar_lancamentos(rows,contas)
        cur.execute('SELECT * FROM lancamentos');existing={x['linha_id']:dict(x) for x in cur.fetchall()}
        documents={x['documento_id'] for x in existing.values()}
        novas=[]
        for x in rows:
            antigo=existing.get(x['linha_id'])
            if antigo:
                antigo['data']=antigo['data'].isoformat()
                if any(antigo[k]!=x[k] for k in CAMPOS):raise ValueError('Identificador existente com conteúdo diferente: '+x['linha_id'])
            else:
                if x['documento_id'] in documents: raise ValueError('Documento existente: não é permitido acrescentar linhas por importação.')
                if x['tipo']=='abertura':raise ValueError('A abertura já existe. Uma segunda abertura não é permitida.')
                novas.append(x)
        for x in novas:
            cur.execute('INSERT INTO lancamentos VALUES ('+','.join(['%s']*len(CAMPOS))+')',tuple(x[k] for k in CAMPOS))
        cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Importação',Json({'linhas':len(existing)}),Json({'linhas':len(existing)+len(novas),'novas':len(novas),'ignoradas':len(rows)-len(novas)})))
    return len(novas),len(rows)-len(novas)

def validar_extrato(rows):
    ids=set()
    for x in rows:
        if not {'registro_id','referencia','valor_centavos','data'}<=set(x):raise ValueError('Use o modelo de extrato.')
        if not x['registro_id'] or x['registro_id'] in ids:raise ValueError('Identificador de registro duplicado.')
        ids.add(x['registro_id'])
        if not x['referencia'] or len(x['referencia'])>100:raise ValueError('Referência inválida.')
        if not re.fullmatch(r'-?\d{1,12}',str(x['valor_centavos'])):raise ValueError('Valor deve estar em centavos.')
        x['valor_centavos']=int(x['valor_centavos'])
        try: date.fromisoformat(x['data'])
        except ValueError:raise ValueError('Data inválida no extrato.')
    return rows
