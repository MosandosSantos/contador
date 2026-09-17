"""Cadastro da empresa, participantes e usuários da instância (Release 1)."""
import re
from flask import Blueprint, request, render_template, redirect, flash
from flask_login import login_required, current_user
from flask_bcrypt import check_password_hash, generate_password_hash
from psycopg2.extras import Json
from core.db import fetch, connection
from core.formularios import resposta_edicao
from core.config_empresa import normalizar_documento

configuracoes = Blueprint('configuracoes', __name__)
REGIMES = {'simples': 'Simples Nacional', 'presumido': 'Lucro Presumido',
           'real': 'Lucro Real', 'arbitrado': 'Lucro Arbitrado', 'outro': 'Outro'}
TIPOS_PARTICIPANTE = {'cliente': 'Cliente', 'fornecedor': 'Fornecedor', 'ambos': 'Cliente e fornecedor'}
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
SENHA_RE = re.compile(r'^(?=.*[A-Za-z])(?=.*\d).{8,72}$')


def _login():
    return current_user.get_id()


def _eh_admin():
    rows = fetch('SELECT admin FROM usuarios WHERE email=%s', (_login(),))
    return bool(rows and rows[0]['admin'])


def _primeiro_admin(cur, admin):
    """Na criação: se a tabela está vazia, o primeiro usuário vira admin."""
    if admin:
        return True
    cur.execute('SELECT 1 FROM usuarios LIMIT 1')
    if not cur.fetchone():
        return True
    return False


def _outro_admin_existe(cur, email):
    """Existe algum administrador diferente do e-mail indicado?"""
    cur.execute('SELECT 1 FROM usuarios WHERE admin=true AND email<>%s', (email,))
    return bool(cur.fetchone())


@configuracoes.route('/empresa', methods=['GET', 'POST'])
@login_required
def empresa():
    if request.method == 'POST':
        try:
            dados = _dados_empresa()
            with connection() as conn, conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(20260920)')
                cur.execute('SELECT cnpj,razao_social FROM empresa WHERE id=1')
                antes = cur.fetchone()
                antes_dict = dict(zip(('cnpj', 'razao_social'), antes)) if antes else {}
                cur.execute('''INSERT INTO empresa(id,cnpj,razao_social,nome_fantasia,regime,cep,logradouro,numero,complemento,bairro,municipio,uf,ie,cod_mun)
                               VALUES(1,%(cnpj)s,%(razao_social)s,%(nome_fantasia)s,%(regime)s,%(cep)s,%(logradouro)s,%(numero)s,%(complemento)s,%(bairro)s,%(municipio)s,%(uf)s,%(ie)s,%(cod_mun)s)
                               ON CONFLICT(id) DO UPDATE SET cnpj=excluded.cnpj,razao_social=excluded.razao_social,
                               nome_fantasia=excluded.nome_fantasia,regime=excluded.regime,cep=excluded.cep,logradouro=excluded.logradouro,
                               numero=excluded.numero,complemento=excluded.complemento,bairro=excluded.bairro,
                               municipio=excluded.municipio,uf=excluded.uf,ie=excluded.ie,cod_mun=excluded.cod_mun,
                               atualizado=clock_timestamp()''', dados)
                cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                            ('Cadastro da empresa', Json(antes_dict), Json(dados)))
        except (ValueError, TypeError) as e:
            return resposta_edicao(str(e), '/empresa', erro=True)
        return resposta_edicao('Dados da empresa salvos.', '/empresa')
    row = fetch('SELECT * FROM empresa WHERE id=1')
    dados = dict(row[0]) if row else {}
    return render_template('empresa.html', title='Empresa', active='empresa',
                           e=dados, regimes=REGIMES)


def _dados_empresa():
    texto = lambda k, maximo: request.form.get(k, '').strip()[:maximo]
    cnpj = normalizar_documento(request.form.get('cnpj', ''))
    if not cnpj:
        raise ValueError('Informe o CNPJ da empresa.')
    razao = texto('razao_social', 200)
    if not razao:
        raise ValueError('Informe a razão social.')
    regime = request.form.get('regime', '')
    if regime not in REGIMES:
        raise ValueError('Selecione o regime tributário.')
    cep = ''.join(ch for ch in texto('cep', 20) if ch.isdigit())
    if cep and len(cep) != 8:
        raise ValueError('CEP deve ter 8 dígitos.')
    uf = texto('uf', 2).upper()
    if uf and (len(uf) != 2 or not uf.isalpha()):
        raise ValueError('UF deve ter 2 letras.')
    ie = ''.join(ch for ch in texto('ie', 20) if ch.isdigit() or ch in 'XP')
    cod_mun = ''.join(ch for ch in texto('cod_mun', 7) if ch.isdigit())
    if cod_mun and len(cod_mun) != 7:
        raise ValueError('Código do município (IBGE) deve ter 7 dígitos.')
    return dict(cnpj=cnpj, razao_social=razao, nome_fantasia=texto('nome_fantasia', 200),
                regime=regime, cep=cep, logradouro=texto('logradouro', 200),
                numero=texto('numero', 20), complemento=texto('complemento', 100),
                bairro=texto('bairro', 100), municipio=texto('municipio', 100), uf=uf,
                ie=ie, cod_mun=cod_mun)


@configuracoes.route('/participantes', methods=['GET', 'POST'])
@login_required
def participantes():
    if request.method == 'POST':
        operacao = request.form.get('operacao', '')
        try:
            documento = normalizar_documento(request.form.get('documento', ''))
            nome = request.form.get('nome', '').strip()[:200]
            if not nome:
                raise ValueError('Informe o nome do participante.')
            tipo = request.form.get('tipo', '')
            if tipo not in TIPOS_PARTICIPANTE:
                raise ValueError('Selecione o tipo do participante.')
            ie = ''.join(ch for ch in request.form.get('ie', '').strip()[:20] if ch.isdigit() or ch in 'XP')
            uf_p = request.form.get('uf', '').strip().upper()[:2]
            cod_mun = ''.join(ch for ch in request.form.get('cod_mun', '').strip()[:7] if ch.isdigit())
            if cod_mun and len(cod_mun) != 7:
                raise ValueError('Código do município (IBGE) deve ter 7 dígitos.')
            chave = documento or nome.casefold()
            with connection() as conn, conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(20260921)')
                if operacao == 'criar':
                    cur.execute('SELECT 1 FROM participantes WHERE chave=%s', (chave,))
                    if cur.fetchone():
                        raise ValueError('Participante já cadastrado com esse documento ou nome.')
                    cur.execute('INSERT INTO participantes(chave,documento,nome,tipo,ie,uf,cod_mun) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                                (chave, documento, nome, tipo, ie, uf_p, cod_mun))
                    antes = {}
                elif operacao == 'editar':
                    chave_original = request.form.get('chave_original', '').strip()[:200]
                    cur.execute('SELECT chave,documento,nome,tipo FROM participantes WHERE chave=%s', (chave_original,))
                    achou = cur.fetchone()
                    if not achou:
                        raise ValueError('Participante não encontrado.')
                    antes = dict(achou)
                    cur.execute('UPDATE participantes SET chave=%s,documento=%s,nome=%s,tipo=%s,ie=%s,uf=%s,cod_mun=%s WHERE chave=%s',
                                (chave, documento, nome, tipo, ie, uf_p, cod_mun, chave_original))
                else:
                    raise ValueError('Operação inválida.')
                depois = dict(chave=chave, documento=documento, nome=nome, tipo=tipo, ie=ie, uf=uf_p, cod_mun=cod_mun)
                cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                            ('Cadastro de participante', Json(antes), Json(depois)))
        except (ValueError, TypeError) as e:
            return resposta_edicao(str(e), '/participantes', erro=True)
        return resposta_edicao('Participante salvo.', '/participantes')
    busca = request.args.get('q', '').strip().casefold()
    rows = fetch('SELECT * FROM participantes ORDER BY nome')
    if busca:
        rows = [r for r in rows if busca in r['nome'].casefold() or busca in (r['documento'] or '').casefold()]
    return render_template('participantes.html', title='Participantes', active='participantes',
                           rows=rows, tipos=TIPOS_PARTICIPANTE, q=busca)


@configuracoes.route('/usuarios', methods=['GET', 'POST'])
@login_required
def usuarios():
    if request.method == 'POST':
        operacao = request.form.get('operacao', '')
        try:
            email = request.form.get('email', '').strip().casefold()
            if not EMAIL_RE.fullmatch(email) or len(email) > 200:
                raise ValueError('Informe um e-mail válido.')
            if operacao != 'senha' and not _eh_admin():
                raise ValueError('Somente administradores gerenciam usuários.')
            with connection() as conn, conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(20260922)')
                if operacao == 'criar':
                    senha = request.form.get('senha', '')
                    if not SENHA_RE.fullmatch(senha):
                        raise ValueError('A senha precisa ter ao menos 8 caracteres com letras e números.')
                    admin = request.form.get('admin') == '1'
                    cur.execute('SELECT 1 FROM usuarios WHERE email=%s', (email,))
                    if cur.fetchone():
                        raise ValueError('Já existe um usuário com esse e-mail.')
                    if not _primeiro_admin(cur, admin):
                        admin = False
                    cur.execute('INSERT INTO usuarios(email,senha_hash,admin,criado_por) VALUES(%s,%s,%s,%s)',
                                (email, generate_password_hash(senha).decode(), admin, _login()))
                    antes, depois = {}, {'email': email, 'admin': admin}
                    mensagem = 'Usuário criado.'
                elif operacao == 'excluir':
                    if email == _login():
                        raise ValueError('Você não pode excluir o próprio usuário.')
                    cur.execute('SELECT admin FROM usuarios WHERE email=%s', (email,))
                    achou = cur.fetchone()
                    if not achou:
                        raise ValueError('Usuário não encontrado.')
                    if achou[0] and not _outro_admin_existe(cur, email):
                        raise ValueError('A instância precisa de ao menos um administrador. Promova outro antes de excluir.')
                    cur.execute('DELETE FROM usuarios WHERE email=%s', (email,))
                    antes, depois = {'email': email}, {}
                    mensagem = 'Usuário excluído.'
                elif operacao == 'admin':
                    if email == _login():
                        raise ValueError('Você não pode alterar o próprio nível de acesso.')
                    admin = request.form.get('admin') == '1'
                    cur.execute('SELECT admin FROM usuarios WHERE email=%s', (email,))
                    if not cur.fetchone():
                        raise ValueError('Usuário não encontrado.')
                    if not admin and not _outro_admin_existe(cur, email):
                        raise ValueError('A instância precisa de ao menos um administrador.')
                    cur.execute('UPDATE usuarios SET admin=%s WHERE email=%s', (admin, email))
                    antes, depois = {'email': email}, {'email': email, 'admin': admin}
                    mensagem = 'Nível de acesso atualizado.'
                elif operacao == 'senha':
                    alvo = email
                    senha = request.form.get('senha', '')
                    if not SENHA_RE.fullmatch(senha):
                        raise ValueError('A senha precisa ter ao menos 8 caracteres com letras e números.')
                    if alvo != _login() and not _eh_admin():
                        raise ValueError('Somente administradores trocam senhas de outros usuários.')
                    cur.execute('SELECT 1 FROM usuarios WHERE email=%s', (alvo,))
                    if not cur.fetchone():
                        raise ValueError('Usuário não encontrado.')
                    cur.execute('UPDATE usuarios SET senha_hash=%s,atualizado=clock_timestamp() WHERE email=%s',
                                (generate_password_hash(senha).decode(), alvo))
                    antes, depois = {'email': alvo}, {'email': alvo}
                    mensagem = 'Senha alterada.'
                else:
                    raise ValueError('Operação inválida.')
                cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                            ('Gestão de usuários', Json(antes), Json(depois)))
        except (ValueError, TypeError) as e:
            return resposta_edicao(str(e), '/usuarios', erro=True)
        return resposta_edicao(mensagem, '/usuarios')
    rows = fetch('SELECT email,admin,criado_por,criado FROM usuarios ORDER BY email')
    return render_template('usuarios.html', title='Usuários', active='usuarios',
                           rows=rows, eu=_login())


@configuracoes.route('/minha-senha', methods=['GET', 'POST'])
@login_required
def minha_senha():
    if request.method == 'POST':
        try:
            atual = request.form.get('atual', '')
            nova = request.form.get('nova', '')
            if not SENHA_RE.fullmatch(nova):
                raise ValueError('A nova senha precisa ter ao menos 8 caracteres com letras e números.')
            if nova != request.form.get('confirmar', ''):
                raise ValueError('A confirmação não confere com a nova senha.')
            rows = fetch('SELECT senha_hash FROM usuarios WHERE email=%s', (_login(),))
            if not rows or not check_password_hash(rows[0]['senha_hash'], atual):
                raise ValueError('Senha atual incorreta.')
            if check_password_hash(rows[0]['senha_hash'], nova):
                raise ValueError('A nova senha precisa ser diferente da atual.')
            with connection() as conn, conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(20260922)')
                cur.execute('UPDATE usuarios SET senha_hash=%s,atualizado=clock_timestamp() WHERE email=%s',
                            (generate_password_hash(nova).decode(), _login()))
                cur.execute('INSERT INTO auditoria(acao,antes,depois) VALUES(%s,%s,%s)',
                            ('Troca de senha', Json({}), Json({'email': _login()})))
        except (ValueError, TypeError) as e:
            return resposta_edicao(str(e), '/minha-senha', erro=True)
        flash('Senha alterada com sucesso.', 'success')
        return redirect('/')
    return render_template('minha_senha.html', title='Minha senha', active='minha-senha')
