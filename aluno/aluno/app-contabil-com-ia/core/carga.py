"""Confere e grava uma carga inteira; a base substituída é arquivada na transação."""
from collections import defaultdict
from datetime import date
import json
from psycopg2.extras import Json, RealDictCursor
from core.db import connection
from core.importacao import CAMPOS,TIPOS
from core.dre_importacao import validar_dre, aplicar_dre
from core.orcamento_importacao import validar_orcamento, aplicar_orcamento

CONTA_CAMPOS=['conta_id','descricao','grupo','componente','linha_dre','analitica','conta_pai_id','ordem','nivel','natureza','classe_bp','cod_referencial']
GRUPOS={'ativo','passivo','pl','resultado','pendente'}

def conta_normalizada(c):
    d=dict(conta_id=str(c['conta_id']).strip(),descricao=str(c.get('descricao') or c['conta_id']).strip(),grupo=c.get('grupo') or 'pendente',componente=c.get('componente') or '',linha_dre=c.get('linha_dre') or '',analitica=c.get('analitica',True),conta_pai_id=c.get('conta_pai_id') or '',ordem=int(c.get('ordem') or 100),nivel=int(c.get('nivel') or 1),natureza=c.get('natureza') or '',classe_bp=c.get('classe_bp') or 'pendente',cod_referencial=str(c.get('cod_referencial') or '').strip()[:60])
    if d['grupo'] not in GRUPOS:raise ValueError('Grupo patrimonial inválido na conta '+d['conta_id'])
    if not d['conta_id'] or len(d['conta_id'])>100 or len(d['descricao'])>300:raise ValueError('Código/descrição de conta inválidos.')
    if d['classe_bp'] not in ('circulante','nao_circulante','pl','resultado','pendente'):raise ValueError('Classe de balanço inválida.')
    if d['grupo'] in ('pl','resultado'):d['classe_bp']=d['grupo']
    elif d['grupo'] in ('ativo','passivo') and d['classe_bp'] not in ('circulante','nao_circulante','pendente'):raise ValueError('Ativo/passivo deve ser circulante, não circulante ou pendente.')
    if not 1<=d['nivel']<=20 or not 0<=d['ordem']<=99999:raise ValueError('Nível ou ordem da conta inválidos.')
    return d

def conferir(payload,existentes=()):
    rows=payload['rows'];ids=set();docs=defaultdict(list)
    catalogo={c['conta_id']:conta_normalizada(c) for c in existentes}
    informadas=payload.get('contas',[])
    if len({c['conta_id'] for c in informadas})!=len(informadas):raise ValueError('Conta repetida no catálogo do arquivo.')
    for c in informadas:catalogo[c['conta_id']]=conta_normalizada(c)
    for i,x in enumerate(rows,2):
        if set(x)!=set(CAMPOS):raise ValueError(f'Linha {i}: colunas inválidas.')
        if not x['linha_id'] or x['linha_id'] in ids:raise ValueError(f'Linha {i}: identificador vazio ou repetido.')
        ids.add(x['linha_id'])
        try:dt=date.fromisoformat(x['data'])
        except (TypeError,ValueError):raise ValueError(f'Linha {i}: data inválida.')
        if not 1900<=dt.year<=2199:raise ValueError(f'Linha {i}: ano fora de 1900–2199.')
        if x['tipo'] not in TIPOS:raise ValueError(f'Linha {i}: tipo {x["tipo"]!r} não reconhecido.')
        if any(not isinstance(x[k],int) or isinstance(x[k],bool) or not 0<=x[k]<=999999999999 for k in ('debito_centavos','credito_centavos')):raise ValueError(f'Linha {i}: valor inválido.')
        if bool(x['debito_centavos'])==bool(x['credito_centavos']):raise ValueError(f'Linha {i}: informe só um lado positivo.')
        if any(len(str(v))>1000 for v in x.values()):raise ValueError(f'Linha {i}: campo excessivamente longo.')
        if not x['documento_id'] or not x['conta_id']:raise ValueError(f'Linha {i}: documento e conta são obrigatórios.')
        if x['conta_id'] not in catalogo:catalogo[x['conta_id']]=conta_normalizada({'conta_id':x['conta_id']})
        if not catalogo[x['conta_id']]['analitica']:raise ValueError('Lançamento em conta sintética: '+x['conta_id'])
        docs[(x['empresa_id'],x['documento_id'])].append(x)
    if len({x['empresa_id'] for x in rows})!=1:raise ValueError('Importe uma empresa por base.')
    for (_,doc),xs in docs.items():
        if len({x['data'] for x in xs})!=1:raise ValueError('Documento com datas distintas: '+doc)
        delta=sum(x['debito_centavos']-x['credito_centavos'] for x in xs)
        if delta:
            source=payload.get('origem_linhas',{}).get(doc,[])
            detalhe=(' · MOVIMENTOS, linhas '+', '.join(str(n) for n in source if n)) if source else ''
            valor=f'{abs(delta)/100:,.2f}'.replace(',','_').replace('.',',').replace('_','.')
            raise ValueError('Documento desbalanceado: '+doc+detalhe+'. Diferença de R$ '+valor+'. Corrija a origem e reenvie; nenhum lançamento foi gravado.')
    for c in catalogo.values():
        seen={c['conta_id']};pai=c['conta_pai_id']
        while pai:
            if pai in seen:raise ValueError('Ciclo na hierarquia de contas: '+c['conta_id'])
            if pai not in catalogo:raise ValueError('Conta pai inexistente: '+pai)
            if catalogo[pai]['analitica']:raise ValueError('Conta pai deve ser sintética: '+pai)
            seen.add(pai);pai=catalogo[pai]['conta_pai_id']
    from core.arvore import linearizar
    return [conta_normalizada(c) for c in linearizar(list(catalogo.values()))]

def gravar(payload,modo,*,arquivo=None,usuario=None):
    if modo not in ('acrescentar','substituir'):raise ValueError('Escolha como usar o arquivo.')
    with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT pg_advisory_xact_lock(20260911)')
        cur.execute('SELECT * FROM contas');antigas=[dict(x) for x in cur.fetchall()]
        catalogo=conferir(payload,antigas if modo=='acrescentar' else ())
        validar_orcamento(payload.get('orcamento'), catalogo)
        cur.execute('SELECT * FROM dre_grupos');grupos_anteriores=[dict(x) for x in cur.fetchall()]
        validar_dre(payload.get('dre'),grupos_anteriores,modo)
        cur.execute('SELECT * FROM lancamentos');old=[dict(x) for x in cur.fetchall()]
        linhas_antes=len(old)
        for x in old:x['data']=x['data'].isoformat()
        if modo=='acrescentar' and old and {x['empresa_id'] for x in old}!={x['empresa_id'] for x in payload['rows']}:raise ValueError('A empresa difere da base atual. Use substituir para manter bases separadas.')
        if modo=='substituir':
            archive={'lancamentos':old,'contas':antigas}
            for table in ('orcamento','reclassificacoes','dre_grupos','dre_vinculos','dre_contas_config','dre_centros_config','centros','conciliacao','regras_centros'):
                cur.execute('SELECT * FROM '+table);archive[table]=[dict(x) for x in cur.fetchall()]
            archive=json.loads(json.dumps(archive,default=str))
            cur.execute('INSERT INTO bases_arquivadas(motivo,conteudo) VALUES(%s,%s)',('Substituição por importação',Json(archive)))
            for table in ('regras_centros','dre_vinculos','reclassificacoes','orcamento','lancamentos','contas','centros'):cur.execute('DELETE FROM '+table)
            if payload.get('dre') and payload['dre']['grupos'] is not None:
                cur.execute('DELETE FROM dre_grupos')
            cur.execute("UPDATE conciliacao SET extrato='[]'::jsonb WHERE id=1")
            old=[]
        existing={x['linha_id']:x for x in old};docs={x['documento_id'] for x in old}
        novas=[]
        for x in payload['rows']:
            if x['linha_id'] in existing:
                if any(x[k]!=existing[x['linha_id']][k] for k in CAMPOS):raise ValueError('Identificador já existente com conteúdo diferente: '+x['linha_id'])
            elif x['documento_id'] in docs:raise ValueError('Documento já existente: '+x['documento_id'])
            else:novas.append(x)
        for c in catalogo:
            # Acrescentar nunca reclassifica silenciosamente o cadastro existente.
            cur.execute('INSERT INTO contas('+','.join(CONTA_CAMPOS)+') VALUES('+','.join(['%s']*len(CONTA_CAMPOS))+') ON CONFLICT(conta_id) DO NOTHING',tuple(c[k] for k in CONTA_CAMPOS))
        # Conferir também a estrutura efetivamente persistida: acrescentar preserva
        # o cadastro existente e não pode trocar seu tipo apenas durante a validação.
        cur.execute('SELECT * FROM contas');persistidas=[dict(x) for x in cur.fetchall()]
        conferir(dict(payload,contas=[]),persistidas)
        for x in novas:
            cur.execute('INSERT INTO lancamentos('+','.join(CAMPOS)+') VALUES('+','.join(['%s']*len(CAMPOS))+')',tuple(x[k] for k in CAMPOS))
        cur.execute("INSERT INTO centros SELECT DISTINCT centro_id,centro_id FROM lancamentos WHERE centro_id<>'' ON CONFLICT DO NOTHING")
        for centro in payload.get('centros', []):
            codigo=str(centro.get('centro_id','')).strip();descricao=str(centro.get('descricao') or codigo).strip()
            if not codigo or len(codigo)>100 or len(descricao)>300:raise ValueError('Código ou descrição de centro inválido na planilha.')
            cur.execute('INSERT INTO centros VALUES(%s,%s) ON CONFLICT(centro_id) DO UPDATE SET descricao=CASE WHEN centros.descricao=centros.centro_id THEN excluded.descricao ELSE centros.descricao END',(codigo,descricao))
        resumo_dre = aplicar_dre(cur,payload.get('dre'),modo)
        resumo_orcamento = aplicar_orcamento(cur,payload.get('orcamento'),modo)
        cur.execute("INSERT INTO dre_vinculos SELECT c.conta_id,'',g.codigo FROM contas c JOIN dre_grupos g ON g.codigo=c.linha_dre WHERE c.grupo='resultado' AND c.analitica AND g.tipo='detalhe' AND NOT EXISTS(SELECT 1 FROM dre_contas_config d WHERE d.conta_id=c.conta_id) ON CONFLICT DO NOTHING")
        registro={'linhas':len(old)+len(novas),'novas':len(novas),'ignoradas':len(payload['rows'])-len(novas),
                  'modo':modo,'recebidas':len(payload['rows']),
                  'inicio':min(x['data'] for x in payload['rows']),'fim':max(x['data'] for x in payload['rows']),
                  'arquivo':str(arquivo).replace('\\','/').rsplit('/',1)[-1][:200] if arquivo else None,
                  'usuario':usuario}
        if payload.get('dre') is not None:registro['dre']=resumo_dre
        if payload.get('orcamento') is not None:registro['orcamento']=resumo_orcamento
        cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',('Importação',Json({'linhas':linhas_antes}),Json(registro)))
    return len(novas),len(payload['rows'])-len(novas)
