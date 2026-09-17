"""Conversa financeira: o modelo escolhe a consulta, o app calcula os números."""
import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from datetime import date

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from core import nvidia_chat
from core import conversa_dados

analise_financeira = Blueprint('analise_financeira', __name__)
_lock = threading.Lock()
_ativos = set()
_ritmo = {}
_diario = {}
_cache = OrderedDict()


def contexto():
    from core.db import fetch
    carga = fetch('SELECT min(data) AS inicio,max(data) AS fim FROM lancamentos')[0]
    fim = str(carga['fim']) if carga['fim'] else None
    anos = list(range(carga['inicio'].year, carga['fim'].year + 1)) if fim else []
    return dict(active='analise', title='Análise financeira', ia_status=nvidia_chat.status(),
                ultimo_importado=fim, anos=anos)


def explicacao_calculada(quadro):
    pontos = [p for p in quadro['pontos'] if p['valor'] is not None]
    if not pontos:
        return 'Não há valores suficientes para esta análise. Confira a classificação e o período nos dados do quadro.'
    def fmt(v):
        return f'{v:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    p = pontos[-1]
    valor = fmt(p['valor']) + (' vezes' if quadro['unidade'] == 'indice' else '%') if quadro['unidade'] in ('indice','percentual') else ('R$ ' + fmt(p['valor'] / 100))
    texto = f"{quadro['titulo']}: {p['label']} registra {valor}."
    if p.get('variacao_percentual') is not None:
        texto += f" Variação de {fmt(p['variacao_percentual'])}% em relação ao período anterior comparável."
    if p.get('parcial'):
        texto += ' Esse período está incompleto; não deve ser comparado diretamente com um período inteiro.'
        completos = [x for x in pontos if not x.get('parcial') and x.get('variacao_percentual') is not None]
        if completos:
            fechado = completos[-1]
            texto += f" Entre os períodos completos, {fechado['label']} variou {fmt(fechado['variacao_percentual'])}% sobre o anterior."
    return texto + ' Fórmula e valores de origem estão disponíveis abaixo do gráfico.'


def _reservar(usuario, ip):
    agora = time.monotonic()
    hoje = date.today().isoformat()
    with _lock:
        if usuario in _ativos: return 'Aguarde a resposta da pergunta anterior.'
        # Limites por processo, adequados à instância única do workshop.
        for chave in (('usuario', usuario), ('ip', ip)):
            q = _ritmo.setdefault(chave, deque())
            while q and agora - q[0] > 60: q.popleft()
            if len(q) >= 8: return 'Muitas perguntas em sequência. Aguarde um minuto.'
        diario = _diario.get(usuario, (hoje, 0))
        if diario[0] != hoje: diario = (hoje, 0)
        if diario[1] >= 150: return 'O limite diário de perguntas desta instância foi atingido.'
        for chave in (('usuario', usuario), ('ip', ip)): _ritmo[chave].append(agora)
        _diario[usuario] = (hoje, diario[1] + 1)
        _ativos.add(usuario)
    return None


@analise_financeira.post('/api/analise/chat')
@login_required
def perguntar():
    if request.content_length and request.content_length > 16000:
        return jsonify(erro='A pergunta é muito longa.'), 400
    entrada = request.get_json(silent=True)
    if not isinstance(entrada, dict) or set(entrada) - {'pergunta', 'contexto', 'historico'}:
        return jsonify(erro='Envie uma pergunta e o contexto da conversa.'), 400
    pergunta = entrada.get('pergunta')
    if not isinstance(pergunta, str) or not 2 <= len(pergunta.strip()) <= 1000:
        return jsonify(erro='Escreva uma pergunta com até 1.000 caracteres.'), 400
    pergunta = pergunta.strip()
    from modules.pages import source
    mov, contas, orcamento = source()
    from core.db import fetch
    from core.estrutura_dre import com_coringa, vinculos_efetivos
    grupos=com_coringa(fetch('SELECT codigo,nome,ordem,tipo FROM dre_grupos ORDER BY ordem,codigo'))
    vinculos=vinculos_efetivos(fetch('SELECT conta_id,centro_id,grupo_codigo FROM dre_vinculos'),fetch('SELECT * FROM dre_contas_config'),fetch('SELECT * FROM dre_centros_config'))
    centros=fetch('SELECT centro_id,descricao FROM centros')
    consulta=conversa_dados.Consulta(mov,contas,orcamento,grupos,vinculos,centros)
    historico=entrada.get('historico',[])
    if not isinstance(historico,list) or len(historico)>6:
        return jsonify(erro='Histórico de conversa inválido.'),400
    for item in historico:
        if not isinstance(item,dict) or set(item)!={'role','text'} or item.get('role') not in ('user','assistant') or not isinstance(item.get('text'),str) or len(item['text'])>1000:
            return jsonify(erro='Histórico de conversa inválido.'),400
    if not mov:
        return jsonify(erro='Importe os lançamentos antes de iniciar a análise.'), 400
    ultimo = max(str(x['data'])[:10] for x in mov)
    try:
        anterior = conversa_dados.validar_plano(entrada['contexto'], consulta.cat, ultimo) if entrada.get('contexto') is not None else None
    except (ValueError, TypeError):
        return jsonify(erro='O contexto da conversa é inválido. Comece um novo chat.'), 400
    usuario = current_user.get_id()
    falha = _reservar(usuario, request.remote_addr or '')
    if falha: return jsonify(erro=falha), 429
    try:
        cfg = nvidia_chat.status()
        # Cache nunca reutiliza respostas após importar, limpar ou reclassificar.
        bruto = json.dumps([usuario, pergunta, anterior, historico, mov, contas, orcamento, grupos, vinculos, centros, cfg], sort_keys=True, default=str, ensure_ascii=False)
        chave = hashlib.sha256(bruto.encode()).hexdigest()
        with _lock:
            encontrado = _cache.get(chave)
        if encontrado and time.monotonic() - encontrado[0] < 300:
            return jsonify(encontrado[1])
        avisos = []
        modo = 'calculado'
        plano = conversa_dados.continuacao_explicita(pergunta,anterior,consulta.cat,ultimo)
        if cfg['configurada'] and plano is None:
            try:
                proposta=nvidia_chat.planejar_dados(pergunta,anterior,consulta.cat,ultimo,historico)
                if isinstance(proposta,dict) and set(proposta)=={'esclarecimento'}:
                    return jsonify(resposta=proposta['esclarecimento'],modo='nvidia',plano=anterior,quadro=None,quadros=[],avisos=[])
                plano=conversa_dados.validar_plano(proposta,consulta.cat,ultimo)
            except nvidia_chat.ServicoIA as exc:
                avisos.append('Na interpretação da pergunta: '+str(exc))
            except (ValueError,TypeError) as exc:
                avisos.append('A consulta proposta pela IA não pôde ser calculada: '+str(exc))
        elif not cfg['configurada']:
            avisos.append('IA não conectada. Configure sua chave NVIDIA para conversar em linguagem livre.')
        if plano is None:plano=conversa_dados.plano_local(pergunta,anterior,consulta.cat,ultimo)
        if plano is None:
            return jsonify(resposta='Não consegui definir o cálculo desta pergunta. Indique quais contas, componentes ou linhas dos relatórios deseja relacionar e o período; posso combinar seus saldos, movimentos e orçamento.',modo='calculado',plano=anterior,quadro=None,quadros=[],avisos=avisos)
        quadros=consulta.construir(plano)
        resposta='\n\n'.join(explicacao_calculada(q) for q in quadros)
        if cfg['configurada']:
            try:
                resposta=nvidia_chat.explicar_dados(pergunta,quadros,historico)
                modo='nvidia'
            except nvidia_chat.ServicoIA as exc:
                avisos.append('Na explicação: '+str(exc)+' Os cálculos e as fontes estão no quadro.')
        saida=dict(resposta=resposta,modo=modo,plano=plano,quadro=quadros[0],quadros=quadros,avisos=avisos)
        # Não memoriza falhas transitórias do provedor.
        if not avisos and (not cfg['configurada'] or modo == 'nvidia'):
            with _lock:
                _cache[chave] = (time.monotonic(), saida)
                while len(_cache) > 128: _cache.popitem(last=False)
        return jsonify(saida)
    except ValueError as e:
        return jsonify(erro=str(e)), 400
    finally:
        with _lock: _ativos.discard(usuario)
