"""Correções gerenciais explícitas, sem reescrever o lançamento original."""
def aplicar_regras(mov,regras):
    regras=sorted(regras,key=lambda x:x['prioridade'])
    out=[]
    for original in mov:
        x=dict(original);x['centro_original']=x.get('centro_id','');x['regra_centro_id']=None
        data=str(x['data'])[:10]
        for r in regras:
            if (not r['conta_id'] or r['conta_id']==x['conta_id']) and r['centro_origem']==x['centro_original'] and str(r['inicio'])[:10]<=data<=str(r['fim'])[:10]:
                x['centro_id']=r['centro_destino'];x['regra_centro_id']=r['id'];break
        out.append(x)
    return out

def classificar(mov):
    from core.db import fetch
    return aplicar_regras(mov,fetch('SELECT * FROM regras_centros ORDER BY prioridade'))
