#!/usr/bin/env python3
"""Montagem aditiva do template validado. Não abre banco nem executa sementes."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
import re
import socket
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'assets/template.zip'
MARCADOR = '.app-contabil-template.json'
ESTADO = 'config/modulos.json'
ORDEM = ('conciliacao', 'importacao-cadastros', 'balancete', 'razao', 'balanco', 'dre-referencia', 'dre-gerencial', 'dmpl', 'fluxos', 'orcamento', 'analise-ia', 'fiscal', 'publicacao')
DEPENDENCIAS = {m: ('conciliacao',) for m in ORDEM}
DEPENDENCIAS.update(conciliacao=(), **{m: ('importacao-cadastros',) for m in ORDEM[2:9]})
DEPENDENCIAS.update({'orcamento': ('dre-gerencial',), 'analise-ia': ('importacao-cadastros',), 'fiscal': ('importacao-cadastros',), 'publicacao': ('conciliacao',)})
BASE = ('.dockerignore', '.env.example', '.gitignore', 'README.md', 'requirements.txt', 'THIRD_PARTY_NOTICES.md', 'app.py', 'config/app.json', 'scripts/schema.sql', 'scripts/local.py', 'scripts/preparar.py', 'iniciar.bat', 'parar.bat', 'preparar_ambiente.bat', 'core/', 'modules/', 'dados/', 'static/', 'templates/base.html', 'templates/login.html', 'templates/error.html', 'templates/home.html')
ARQUIVOS = {
    'conciliacao': ('templates/conciliacao_upload.html', 'templates/conciliacao_resultado.html', 'templates/conciliacao_detalhe.html'),
    'importacao-cadastros': ('templates/importar.html', 'templates/historico_importacoes.html', 'templates/contas.html', 'templates/centros.html', 'templates/limpar.html'),
    'balancete': ('templates/balancete_arvore.html', 'templates/sem_base.html'),
    'razao': ('templates/razao_secoes.html', 'templates/sem_base.html'),
    'balanco': ('templates/relatorio_periodo.html', 'templates/sem_base.html'),
    'dre-referencia': ('templates/relatorio_periodo.html', 'templates/sem_base.html'),
    'dre-gerencial': ('templates/dre_gerencial.html', 'templates/grupos_dre.html', 'templates/sem_base.html'),
    'dmpl': ('templates/relatorio_periodo.html', 'templates/sem_base.html'),
    'fluxos': ('templates/fluxo_caixa.html', 'templates/sem_base.html'),
    'orcamento': ('templates/orcado_realizado.html', 'templates/sem_base.html'),
    'analise-ia': ('templates/analise_chat.html', 'templates/configuracao_ia.html', 'configurar_ia.bat', 'scripts/configurar_ia.py'),
    'fiscal': ('core/ecf.py', 'core/ecd.py', 'core/efd_contribuicoes.py', 'core/efd_icms_ipi.py', 'core/esocial.py',
               'modules/ecf.py', 'modules/efd.py', 'modules/esocial.py',
               'templates/ecf.html', 'templates/efd_contribuicoes.html', 'templates/efd_icms_ipi.html', 'templates/esocial.html',
               'scripts/validar_ecd.py', 'scripts/validar_ecf.py', 'scripts/validar_efd_contribuicoes.py', 'scripts/validar_efd_icms_ipi.py', 'scripts/validar_esocial.py'),
    'publicacao': ('Dockerfile', 'docs/EASYPANEL.md'),
}
PONTES = ('atualizar.bat', 'scripts/atualizar.py', 'scripts/atualizar_selecionar.py', 'publicar.bat', 'scripts/empacotar_publicacao.py', 'scripts/progressao.py', 'scripts/zipar_app.py', 'scripts/personalizar_nome.py')
IDENTIDADE_FONTE = {'app.py': 'fa7eb2b7e4a4e5d7d861149da343d41885f5aa059e27884af4a6bafc062b8430', 'templates/base.html': '69feef5eadd25a083bc2524a1dea699f0206a4df9ab23c82d406469e8e562898'}

def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def json_bytes(d: dict) -> bytes:
    return (json.dumps(d, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

def seguro(nome: str) -> bool:
    if not isinstance(nome, str) or not nome or any(c in nome for c in '\\:"<>|?*') or any(ord(c) < 32 for c in nome):
        return False
    p = PurePosixPath(nome)
    reservados = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{t}{i}' for t in ('COM', 'LPT') for i in range(1, 10)}
    return not p.is_absolute() and str(p) == nome and all(v not in ('.', '..') and not v.endswith((' ', '.')) and v.split('.')[0].upper() not in reservados for v in p.parts)

def permitido(nome: str) -> bool:
    if not seguro(nome):
        return False
    if nome in {'config/app.json', ESTADO, MARCADOR, 'app.py', 'README.md', 'requirements.txt', 'THIRD_PARTY_NOTICES.md', 'Dockerfile', '.dockerignore', '.env.example', '.gitignore', 'iniciar.bat', 'parar.bat', 'preparar_ambiente.bat', 'atualizar.bat', 'publicar.bat', 'configurar_ia.bat'}:
        return True
    p = PurePosixPath(nome)
    extensoes = {'core': {'.py'}, 'modules': {'.py'}, 'templates': {'.html'}, 'static': {'.css', '.js', '.woff', '.woff2', '.ttf', '.svg', '.png', '.ico', '.txt', '.eot'}, 'dados': {'.json'}, 'docs': {'.md'}, 'scripts': {'.py', '.sql'}}
    return p.parts[0] in extensoes and p.suffix.lower() in extensoes[p.parts[0]] and not any(x.startswith('.') or x == '__pycache__' for x in p.parts)

def caminho(app: Path, nome: str) -> Path:
    if not permitido(nome):
        raise ValueError('Caminho fora da lista permitida: ' + str(nome))
    alvo = app.joinpath(*PurePosixPath(nome).parts)
    for p in [alvo, *alvo.parents]:
        if p == app.parent:
            break
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('Link de sistema não permitido: ' + str(p))
    if not alvo.resolve().is_relative_to(app.resolve()):
        raise ValueError('Caminho escapa da pasta do aplicativo.')
    return alvo

def modulos_com_dependencias(modulos: list[str]) -> list[str]:
    resultado = set()
    def incluir(m):
        if m not in ORDEM:
            raise ValueError('Módulo inválido: ' + str(m))
        if m not in resultado:
            resultado.add(m)
            for d in DEPENDENCIAS[m]:
                incluir(d)
    for m in modulos:
        incluir(m)
    return [m for m in ORDEM if m in resultado]

def estado(app: Path) -> dict:
    try:
        valor = json.loads(caminho(app, ESTADO).read_text(encoding='utf-8'))
        marcador = json.loads(caminho(app, MARCADOR).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('Estado ou marcador ausente/inválido.') from exc
    if not isinstance(valor, dict) or not isinstance(marcador, dict) or valor.get('schema') != 2 or marcador.get('schema') != 2 or not marcador.get('progressivo'):
        raise ValueError('Cópia incompatível: exige montagem progressiva versão 2.')
    projeto = valor.get('projeto_id')
    if not isinstance(projeto, str) or not re.fullmatch(r'[0-9a-f-]{36}', projeto) or marcador.get('projeto_id') != projeto:
        raise ValueError('Identidade do projeto divergente.')
    modulos = valor.get('habilitados')
    if not isinstance(modulos, list) or not modulos or modulos_com_dependencias(modulos) != modulos:
        raise ValueError('Módulos ou dependências inválidos.')
    arquivos = valor.get('arquivos')
    if not isinstance(arquivos, dict) or not arquivos or not {'app.py', 'templates/base.html', 'core/modulos.py', 'scripts/local.py'} <= arquivos.keys():
        raise ValueError('Manifesto de arquivos inválido.')
    for n, h in arquivos.items():
        caminho(app, n)
        if n in (MARCADOR, ESTADO) or not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h):
            raise ValueError('Hash ou arquivo inválido no manifesto: ' + n)
    if not re.fullmatch(r'[0-9a-f]{64}', str(valor.get('template_sha256', ''))):
        raise ValueError('Identidade do template inválida.')
    return valor

def _selecionados(itens: tuple[str, ...], nomes: list[str]) -> set[str]:
    retorno = set()
    for item in itens:
        encontrados = {n for n in nomes if n.startswith(item)} if item.endswith('/') else {item} & set(nomes)
        if not encontrados:
            raise ValueError('Arquivo/pasta obrigatória ausente na biblioteca: ' + item)
        retorno.update(encontrados)
    return retorno

def substituir(texto, antes, depois):
    if texto.count(antes) != 1:
        raise ValueError('Âncora do template mudou: ' + antes[:90])
    return texto.replace(antes, depois, 1)

def adaptar(nome: str, dados: bytes) -> bytes:
    if nome == 'README.md':
        t = dados.decode('utf-8')
        t = t.replace('A página inicial é **Início**; use **Importar** para trazer a base escolhida para a aula.', 'A página inicial é **Início**. Na primeira entrega, abra **Conciliar → Enviar relatórios** e carregue os dois XLSX. Importar e os demais módulos aparecem após serem pedidos.')
        return (t + '\n## Acrescentar etapas na mesma aplicação\n\nFeche o app com `parar.bat`. Baixe o ZIP da nova versão (não precisa extrair). Na pasta do app, dê dois cliques em `atualizar.bat` e escolha o ZIP baixado. A ponte preserva banco, configuração, chave e anexos e aplica as fontes. Depois, abra `iniciar.bat` para usar. Se houver conflito, nenhum arquivo é atualizado.\n\nAs seções sobre Importar, IA e Docker acima se aplicam quando esses módulos forem acrescentados. A etapa `publicacao` inclui o Dockerfile e o guia de publicação.\n').encode('utf-8')
    if nome not in ('app.py', 'templates/base.html', 'templates/home.html', 'templates/balancete_arvore.html', 'templates/dre_gerencial.html', 'templates/relatorio_periodo.html', 'templates/contas.html', 'templates/centros.html', 'templates/importar.html', 'templates/orcado_realizado.html'):
        return dados
    t = dados.decode('utf-8')
    if nome == 'app.py':
        t = substituir(t, 'from jinja2 import pass_context', 'from jinja2 import pass_context\nfrom core.modulos import instalar, filtrar_nav, filtrar_grupos, disponivel')
        t = substituir(t, 'app=Flask(__name__)', 'app=Flask(__name__)\n    instalar(app)')
        t = substituir(t, 'nav=NAV,menu_grupos=MENU_GRUPOS,', 'nav=filtrar_nav(NAV),menu_grupos=filtrar_grupos(MENU_GRUPOS),modulo_disponivel=disponivel,')
    elif nome == 'templates/base.html':
        for slug in ('limpar', 'configuracao-ia'):
            linhas = [l for l in t.splitlines() if 'href="/' + slug + '"' in l]
            if len(linhas) != 1:
                raise ValueError('Link fixo do rodapé não identificado.')
            t = substituir(t, linhas[0], "        {% if modulo_disponivel('" + slug + "') %}\n" + linhas[0] + '\n        {% endif %}')
    elif nome == 'templates/home.html':
        t = substituir(t, '<aside class="home-base"', "{% if modulo_disponivel('importar') %}<aside class=\"home-base\"")
        t = substituir(t, '</aside>', '</aside>{% endif %}')
        ia = next(l for l in t.splitlines() if '<dt>Inteligência artificial</dt>' in l)
        t = substituir(t, ia, "{% if modulo_disponivel('configuracao-ia') %}" + ia + '{% endif %}')
        t = substituir(t, '{% if tem_base %}Seus números,', "{% if not modulo_disponivel('importar') %}Confira seus relatórios.{% elif tem_base %}Seus números,")
        t = substituir(t, '{% if tem_base %}Confira os demonstrativos,', "{% if not modulo_disponivel('importar') %}Envie as bases contábil e financeira para encontrar diferenças, ausências e duplicidades.{% elif tem_base %}Confira os demonstrativos,")
    elif nome == 'templates/balancete_arvore.html':
        t = substituir(t, '{% if c._url %}', "{% if c._url and modulo_disponivel('razao') %}")
    elif nome == 'templates/relatorio_periodo.html':
        t = substituir(t, '{% if x.conta_id %}', "{% if x.conta_id and modulo_disponivel('razao') %}")
    elif nome == 'templates/dre_gerencial.html':
        t = t.replace('{% if linha.conta_id and ', "{% if modulo_disponivel('razao') and linha.conta_id and ")
        t = t.replace("{% if quadro.origens[mes]=='orcado' and ", "{% if modulo_disponivel('orcamento') and quadro.origens[mes]=='orcado' and ")
        t = re.sub(r'(<a href="/orcamento\?[^>]+>Cadastrar orçamento</a>)', r"{% if modulo_disponivel('orcamento') %}\1{% endif %}", t)
    elif nome == 'templates/orcado_realizado.html':
        t = t.replace('{% if l.conta_id and ', "{% if modulo_disponivel('razao') and l.conta_id and ")
    elif nome == 'templates/importar.html':
        for slug in ('grupos-dre', 'balanco'):
            t = re.sub(r'(<a\b[^>]*href="/' + slug + r'[^>]*>.*?</a>)', "{% if modulo_disponivel('" + slug + "') %}\\1{% endif %}", t)
    else:
        t = re.sub(r'(<a\b[^>]*href="/grupos-dre[^>]*>.*?</a>)', r"{% if modulo_disponivel('grupos-dre') %}\1{% endif %}", t)
    return t.encode('utf-8')

def conteudos(modulos: list[str]) -> tuple[dict[str, bytes], str]:
    manifesto = json.loads((ROOT / 'assets/template-manifest.json').read_text(encoding='utf-8'))
    hash_template = manifesto['sha256']
    pasta = ROOT / 'assets/template'
    if pasta.is_dir():
        # Fonte solta: sem zip aninhado, exigido pelo upload de skill no claude.ai.
        z = None
        nomes = sorted(p.relative_to(pasta).as_posix() for p in pasta.rglob('*') if p.is_file())
        ler = lambda n: (pasta / PurePosixPath(n)).read_bytes()
    else:
        # Compatibilidade: biblioteca ainda empacotada como zip.
        if sha256(TEMPLATE.read_bytes()) != manifesto['sha256']:
            raise ValueError('Biblioteca diferente do manifesto validado.')
        z = zipfile.ZipFile(TEMPLATE)
        nomes = [i.filename for i in z.infolist() if not i.is_dir()]
        ler = lambda n: z.read(n)
    try:
        if len(nomes) != len(set(nomes)) or any(not permitido(n) for n in nomes):
            raise ValueError('Biblioteca contém caminho repetido/fora da lista permitida.')
        for n, h in IDENTIDADE_FONTE.items():
            if sha256(ler(n)) != h:
                raise ValueError('Motor/layout não é a fonte validada: ' + n)
        selecionados = _selecionados(BASE + tuple(n for m in modulos for n in ARQUIVOS[m]), nomes)
        pendentes = list(selecionados)
        while pendentes:
            n = pendentes.pop()
            if n.endswith('.html'):
                for dependencia in re.findall(r'{%\s*(?:extends|include|from|import)\s+[\"\']([^\"\']+)[\"\']', ler(n).decode('utf-8')):
                    rel = 'templates/' + dependencia
                    _selecionados((rel,), nomes)
                    if rel not in selecionados:
                        selecionados.add(rel)
                        pendentes.append(rel)
        arquivos = {}
        for n in sorted(selecionados):
            b = ler(n)
            if sha256(b) != manifesto['files'].get(n):
                raise ValueError('Hash da biblioteca divergente: ' + n)
            arquivos[n] = adaptar(n, b)
    finally:
        if z is not None:
            z.close()
    arquivos['core/modulos.py'] = (ROOT / 'scripts/runtime_modulos.py').read_bytes()
    for n in PONTES:
        arquivos[n] = (ROOT / n).read_bytes()
    return arquivos, hash_template

def verificar_parado(app: Path):
    if (app / '.runtime/app.pid').exists():
        raise ValueError('Estado legado de processo: rode parar.bat e confira a instância.')
    arquivo = app / '.runtime/estado.json'
    if not arquivo.exists():
        return
    try:
        s = json.loads(arquivo.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError('Estado do processo inválido; não é seguro atualizar.') from e
    if not isinstance(s, dict):
        raise ValueError('Estado do processo inválido.')
    pid = s.get('app_pid')
    if pid:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError('PID do aplicativo inválido.')
        if os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                kernel.CloseHandle(ctypes.c_void_p(handle))
                raise ValueError('Aplicativo em execução: rode parar.bat antes de atualizar.')
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except PermissionError as e:
                raise ValueError('Processo existente sem acesso; pare o app.') from e
            else:
                raise ValueError('Aplicativo em execução: rode parar.bat antes de atualizar.')
    porta = s.get('app_port')
    if porta:
        if not isinstance(porta, int) or not 1 <= porta <= 65535:
            raise ValueError('Porta do aplicativo inválida.')
        with socket.socket() as sock:
            sock.settimeout(.3)
            if sock.connect_ex(('127.0.0.1', porta)) == 0:
                raise ValueError('A porta registrada ainda está em uso. Confira parar.bat.')

@contextlib.contextmanager
def trava(app: Path):
    lock = app / '.app-contabil-update.lock'
    try:
        with lock.open('x', encoding='utf-8') as f:
            f.write(str(os.getpid()))
    except FileExistsError as e:
        raise ValueError('Já existe uma atualização em andamento ou interrompida; confira a trava.') from e
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)

def transacao(app: Path, alteracoes: dict[str, bytes]):
    """Prepara tudo antes de gravar; reverte falhas. Estado é o último commit."""
    if not alteracoes:
        return
    with tempfile.TemporaryDirectory(prefix='.atualizacao-', dir=app) as pasta:
        stage = Path(pasta)
        anteriores, diretorios = {}, set()
        for indice, (n, b) in enumerate(alteracoes.items()):
            alvo = caminho(app, n)
            if alvo.exists() and not alvo.is_file():
                raise ValueError('Destino não é arquivo: ' + n)
            anteriores[n] = alvo.read_bytes() if alvo.exists() else None
            (stage / str(indice)).write_bytes(b)
        feitos = []
        try:
            for indice, n in enumerate(alteracoes):
                alvo = caminho(app, n)
                for pai in alvo.parents:
                    if pai == app:
                        break
                    if not pai.exists():
                        diretorios.add(pai)
                alvo.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / str(indice), alvo)
                feitos.append(n)
        except BaseException:
            for n in reversed(feitos):
                alvo = caminho(app, n)
                if anteriores[n] is None:
                    alvo.unlink(missing_ok=True)
                else:
                    alvo.write_bytes(anteriores[n])
            for d in sorted(diretorios, key=lambda p: len(p.parts), reverse=True):
                if d.exists() and not any(d.iterdir()):
                    d.rmdir()
            raise

def criar(app: Path) -> dict:
    app = app.resolve()
    if app.exists():
        raise ValueError('Destino já existe; escolha uma pasta nova.')
    arquivos, h = conteudos(['conciliacao'])
    projeto = str(uuid.uuid4())
    registro = {'schema': 2, 'projeto_id': projeto, 'habilitados': ['conciliacao'], 'template_sha256': h, 'arquivos': {n: sha256(b) for n, b in arquivos.items()}}
    app.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.montagem-', dir=app.parent) as pasta:
        stage = Path(pasta) / 'app'
        stage.mkdir()
        for n, b in arquivos.items():
            p = caminho(stage, n)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
        (stage / ESTADO).write_bytes(json_bytes(registro))
        (stage / MARCADOR).write_bytes(json_bytes({'schema': 2, 'projeto_id': projeto, 'nome_app': 'APP CONTÁBIL COM IA', 'progressivo': True}))
        stage.rename(app)
    return registro

def plano(atual: Path, registro: dict, arquivos: dict[str, bytes]) -> dict[str, bytes]:
    mudancas, conflitos = {}, []
    for n, b in arquivos.items():
        p = caminho(atual, n)
        if n == 'config/app.json' and p.is_file():
            continue
        anterior = registro['arquivos'].get(n)
        if p.exists():
            if not p.is_file():
                conflitos.append(n)
                continue
            real = sha256(p.read_bytes())
            if real == sha256(b):
                continue
            if anterior != real:
                conflitos.append(n)
                continue
        elif anterior:
            conflitos.append(n + ' (removido localmente)')
            continue
        mudancas[n] = b
    if conflitos:
        raise ValueError('Conflito em arquivo personalizado; nenhum arquivo alterado: ' + ', '.join(conflitos))
    return mudancas

def expandir(app: Path, modulos: list[str]) -> dict:
    with trava(app):
        verificar_parado(app)
        registro = estado(app)
        habilitados = modulos_com_dependencias(registro['habilitados'] + modulos)
        arquivos, h = conteudos(habilitados)
        if h != registro['template_sha256']:
            raise ValueError('A cópia usa outra biblioteca; migração explícita necessária.')
        mudancas = plano(app, registro, arquivos)
        novos = [m for m in habilitados if m not in registro['habilitados']]
        novo = dict(registro, habilitados=habilitados, arquivos={n: sha256(b) for n, b in arquivos.items()})
        novo['arquivos']['config/app.json'] = registro['arquivos']['config/app.json']
        if novo != registro:
            mudancas[ESTADO] = json_bytes(novo)
        transacao(app, mudancas)
        return {'novos': novos, 'habilitados': habilitados, 'arquivos_alterados': list(mudancas), 'dados_preservados': True}

def atualizar(origem: Path, destino: Path) -> dict:
    origem, destino = origem.resolve(), destino.resolve()
    if origem == destino or origem.is_relative_to(destino) or destino.is_relative_to(origem):
        raise ValueError('Extraia o ZIP em outra pasta, fora da aplicação original.')
    with trava(destino):
        verificar_parado(destino)
        novo, atual = estado(origem), estado(destino)
        if novo['projeto_id'] != atual['projeto_id'] or novo['template_sha256'] != atual['template_sha256']:
            raise ValueError('O ZIP não pertence à mesma aplicação/biblioteca.')
        if not set(atual['habilitados']) <= set(novo['habilitados']) or not atual['arquivos'].keys() <= novo['arquivos'].keys():
            raise ValueError('Atualização removeria etapas ou arquivos existentes.')
        arquivos = {}
        for n, h in novo['arquivos'].items():
            if n == 'config/app.json':
                continue
            p = caminho(origem, n)
            if not p.is_file() or sha256(p.read_bytes()) != h:
                raise ValueError('Arquivo do ZIP ausente ou diferente do manifesto: ' + n)
            arquivos[n] = p.read_bytes()
        mudancas = plano(destino, atual, arquivos)
        novo['arquivos']['config/app.json'] = atual['arquivos']['config/app.json']
        if novo != atual:
            mudancas[ESTADO] = json_bytes(novo)
        transacao(destino, mudancas)
        return {'atualizado': novo['habilitados'], 'arquivos_alterados': list(mudancas), 'config_preservada': True, 'runtime_preservado': True}
