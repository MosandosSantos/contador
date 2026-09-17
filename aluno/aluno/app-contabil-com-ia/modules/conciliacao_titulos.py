"""Conferência de dois relatórios de títulos, sem alterar a escrituração."""
import csv
import io
from math import ceil
from pathlib import Path
from flask import Blueprint, abort, flash, redirect, render_template, request, Response, url_for
from flask_login import login_required
from psycopg2.extras import Json
from core.db import connection, fetch
from core.conciliacao_titulos import ler_relatorio, conciliar
from modules.pages import queryurl, money

titulos = Blueprint('titulos', __name__)
ROOT = Path(__file__).resolve().parents[1]
STATUS = {'ok': 'Conciliado', 'dif': 'Divergência de valor', 'aberto': 'Em aberto no contábil',
          'nlanc': 'Não lançado no contábil', 'cnpj': 'CNPJ divergente',
          'duplicado': 'Duplicidade na origem', 'ambiguo': 'Correspondência ambígua'}
COLUMNS = [{'key': key, 'label': label, 'numeric': numeric} for key, label, numeric in [
    ('cliente', 'Cliente', False), ('titulo', 'Título', False),
    ('cnpj_contabil', 'CNPJ contábil', False), ('cnpj_financeiro', 'CNPJ financeiro', False),
    ('vc_centavos', 'Contábil', True), ('vf_centavos', 'Financeiro', True),
    ('diferenca_centavos', 'Diferença', True), ('situacao', 'Situação', False)]]
ORIGEM = [{'key': key, 'label': label, 'numeric': key == 'valor_centavos'} for key, label in [
    ('linha_origem', 'Linha',), ('cliente', 'Cliente'), ('cnpj', 'CNPJ'), ('titulo', 'Título'),
    ('emissao', 'Emissão'), ('vencimento', 'Vencimento'), ('baixa', 'Baixa'), ('valor_centavos', 'Valor')]]


def salvo():
    rows = fetch('SELECT arquivos, resultado, atualizado FROM conciliacoes_titulos WHERE id=1')
    return rows[0] if rows else None


def linhas_exibidas(dados):
    return [dict(row, indice=indice, situacao=STATUS[row['st']],
                 _url=url_for('titulos.detalhe', indice=indice))
            for indice, row in enumerate(dados['resultado']['linhas'])]


def filtrar(rows):
    status = request.args.get('status', '')
    if status in STATUS:
        rows = [r for r in rows if r['st'] == status]
    q = request.args.get('q', '').strip().casefold()
    if q:
        rows = [r for r in rows if q in ' '.join(str(r.get(c['key']) or '') for c in COLUMNS).casefold()]
    for c in COLUMNS:
        termo = request.args.get('cf_' + c['key'], '').strip().casefold()
        if termo:
            def texto(r):
                v = r.get(c['key'])
                return (money(v) if c['numeric'] and v is not None else str(v or '')).casefold()
            rows = [r for r in rows if termo in texto(r)]
    key = request.args.get('sort', '')
    if key in {c['key'] for c in COLUMNS}:
        def sort_key(row):
            value = row.get(key)
            return (value is None, value if isinstance(value, (int, float)) else str(value or '').casefold())
        rows = sorted(rows, key=sort_key, reverse=request.args.get('order') == 'desc')
    return rows


def upload_context():
    return dict(title='Enviar relatórios', active='conciliacao-arquivos', existente=salvo())


@titulos.route('/conciliacao-arquivos', methods=['GET', 'POST'])
@login_required
def arquivos():
    if request.method == 'GET':
        return render_template('conciliacao_upload.html', **upload_context())
    try:
        parsed, nomes = {}, {}
        for lado in ('contabil', 'financeiro'):
            file = request.files.get(lado)
            if not file or not file.filename:
                raise ValueError('Envie os dois relatórios: Contábil e Financeiro.')
            nomes[lado] = file.filename.replace('\\', '/').rsplit('/', 1)[-1][:180]
            parsed[lado] = ler_relatorio(file.read(), nomes[lado], lado)
        result = conciliar(parsed['contabil'], parsed['financeiro'])
        dates = sorted({row[key] for rows in parsed.values() for row in rows
                        for key in ('emissao', 'vencimento', 'baixa') if row.get(key)})
        br = lambda d: d[8:10]+'/'+d[5:7]+'/'+d[:4]
        metadata = dict(nomes, linhas_contabil=len(parsed['contabil']), linhas_financeiro=len(parsed['financeiro']),
                        periodo=br(dates[0])+' a '+br(dates[-1]) if dates else 'Sem datas informadas')
        with connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(20260911)')
            cur.execute('''INSERT INTO conciliacoes_titulos(id,arquivos,resultado) VALUES(1,%s,%s)
                ON CONFLICT(id) DO UPDATE SET arquivos=excluded.arquivos,resultado=excluded.resultado,atualizado=now()''',
                        (Json(metadata), Json(result)))
        flash('Relatórios conferidos. Abra um título para examinar as linhas de origem.', 'success')
        return redirect(url_for('titulos.resultado'))
    except ValueError as error:
        flash(str(error), 'error')
        return render_template('conciliacao_upload.html', **upload_context()), 400


@titulos.get('/conciliacao')
@login_required
def resultado():
    data = salvo()
    if not data:
        return render_template('conciliacao_resultado.html', title='Conciliação', active='conciliacao', resultado=False)
    all_rows = linhas_exibidas(data)
    rows = filtrar(all_rows)
    by_status = {st: [r for r in all_rows if r['st'] == st] for st in STATUS}
    soma = lambda st, key: sum(r.get(key) or 0 for r in by_status[st])
    diferenca = sum(abs(r.get('diferenca_centavos') or 0) for r in by_status['dif'])
    # Exposição para revisão. Em grupos incertos, usar o maior lado evita somar
    # os dois lados como perdas distintas. Nunca apresentar isso como ganho.
    revisar = diferenca + soma('aberto', 'vc_centavos') + soma('nlanc', 'vf_centavos')
    for st in ('cnpj', 'duplicado', 'ambiguo'):
        revisar += sum(max(abs(r.get('vc_centavos') or 0), abs(r.get('vf_centavos') or 0)) for r in by_status[st])
    kpis = [
        {'label': 'Conciliado', 'value': soma('ok', 'vc_centavos'), 'hint': f"{len(by_status['ok']):,} de {len(all_rows):,} grupos".replace(',', '.')},
        {'label': 'Divergência de valor', 'value': diferenca, 'hint': f"{len(by_status['dif'])} grupos com diferença"},
        {'label': 'Em aberto no contábil', 'value': soma('aberto', 'vc_centavos'), 'hint': f"{len(by_status['aberto'])} grupos sem correspondência"},
        {'label': 'Não lançado no contábil', 'value': soma('nlanc', 'vf_centavos'), 'hint': f"{len(by_status['nlanc'])} grupos apenas no Financeiro"},
        {'label': 'Montante a investigar', 'value': revisar, 'hint': 'Exposição para revisão; não é ganho nem prejuízo confirmado'},
    ]
    for kpi in kpis:
        kpi['currencycentavos'] = True
    statuses = [{'key': '', 'label': 'Todos', 'count': len(all_rows), 'url': queryurl(status=None, page=1), 'active': not request.args.get('status')}]
    statuses += [{'key': st, 'label': label, 'count': len(by_status[st]),
                  'url': queryurl(status=st, page=1), 'active': request.args.get('status') == st}
                 for st, label in STATUS.items()]
    per_page = request.args.get('per_page', 100, type=int)
    if per_page not in (10, 50, 100, 500):
        per_page = 100
    pages = max(1, ceil(len(rows) / per_page))
    page = min(max(1, request.args.get('page', 1, type=int)), pages)
    return render_template('conciliacao_resultado.html', title='Conciliação', active='conciliacao',
                           resultado=True, arquivos=data['arquivos'], atualizado=data['atualizado'],
                           kpis=kpis, statuses=statuses, columns=COLUMNS,
                           rows=rows[(page-1)*per_page:page*per_page], total=len(rows), total_geral=len(all_rows),
                           page=page, pages=pages, per_page=per_page, queryurl=queryurl,
                           export_url=url_for('titulos.exportar', **request.args.to_dict()))


@titulos.get('/conciliacao/detalhe/<int:indice>')
@login_required
def detalhe(indice):
    data = salvo()
    if not data or indice >= len(data['resultado']['linhas']):
        abort(404)
    row = linhas_exibidas(data)[indice]
    return render_template('conciliacao_detalhe.html', title='Origem do título', active='conciliacao',
                           row=row, arquivos=data['arquivos'], status_label=STATUS[row['st']],
                           columns_origem=ORIGEM, labelsourcefilenames=data['arquivos'])


@titulos.get('/conciliacao/exportar.csv')
@login_required
def exportar():
    data = salvo()
    if not data:
        return redirect(url_for('titulos.arquivos'))
    out = io.StringIO(newline='')
    writer = csv.writer(out, delimiter=';', lineterminator='\r\n')
    writer.writerow([c['label'] for c in COLUMNS] + ['Motivo', 'Linhas contábeis', 'Linhas financeiras'])
    for row in filtrar(linhas_exibidas(data)):
        cells = []
        for column in COLUMNS:
            value = row.get(column['key'])
            if column['numeric']:
                cells.append('' if value is None else f'{value / 100:.2f}'.replace('.', ','))
            else:
                text = str(value or '')
                cells.append("'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text)
        cells += [row.get('motivo', ''), ', '.join(str(x['linha_origem']) for x in row['contabil']),
                  ', '.join(str(x['linha_origem']) for x in row['financeiro'])]
        writer.writerow(cells)
    return Response('\ufeff'+out.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=conciliacao_titulos.csv'})


@titulos.get('/conciliacao/modelo/<lado>.csv')
@login_required
def modelo(lado):
    if lado not in ('contabil', 'financeiro'):
        abort(404)
    # O template não distribui bases do aluno nem o lote de ensaio. Entrega só
    # o layout mínimo aceito pelo importador, para o professor preencher.
    cabecalho = 'Cliente;CNPJ;Título;Emissão;Vencimento;Valor' if lado == 'contabil' else 'Cliente;CNPJ;Título;Baixa;Valor'
    return Response('\ufeff' + cabecalho + '\r\n', mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="modelo_{lado}.csv"'})
