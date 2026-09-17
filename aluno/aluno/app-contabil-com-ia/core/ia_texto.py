"""Texto da IA no app (R3): tom híbrido quando a chave não está configurada.

O plano local é sempre gerado pelo app (determinístico, auditável). A explicação
conversacional usa o modelo configurado; sem chave, a tela convida a configurar.
"""
from core.nvidia_chat import ServicoIA, status as status_ia
from core.modelos_ia import MODELO_PADRAO


def frase_hibrida(modelo=MODELO_PADRAO):
    """Convite padronizado quando o texto conversacional roda sem chave."""
    return ('Estes destaques foram calculados pelo próprio app — auditáveis e sempre disponíveis. '
            f'Para a narrativa conversacional, configure sua chave NVIDIA (recomendamos {modelo}) '
            'em Configuração da IA.')


def status_narrativa():
    """(modo, mensagem_de_aviso) a partir da configuração vigente."""
    st = status_ia()
    if st['configurada']:
        return 'nvidia', None
    return 'local', frase_hibrida(st['modelo'])


def chat_da_analise(dados, pergunta):
    """Explicação da IA sobre números já calculados. Retorna (texto, modo, aviso).

    Modo 'local' devolve plano local + convite; a IA não vê dados crus.
    """
    aviso = None
    try:
        from core.nvidia_chat import explicar_dados
        texto = explicar_dados(
            pergunta or 'Escreva o resumo executivo do mês.',
            [_quadro_narrativa(dados)],
            [],
        )
        return texto, 'nvidia', aviso
    except ServicoIA as exc:
        if exc.codigo != 'nao_configurada':
            aviso = str(exc)
            return _plano_local(dados), 'local', aviso
        return _plano_local(dados), 'local', frase_hibrida()


def _quadro_narrativa(dados):
    """Adapta os agregados do relatório mensal ao formato esperado pelo explicar_dados."""
    comp = dados.get('competencia', '')
    receitas = (dados.get('receitas') or 0) / 100
    despesas = (dados.get('despesas') or 0) / 100
    resultado = (dados.get('resultado') or 0) / 100
    caixa_final = (dados.get('caixa_final') or 0) / 100
    variacao = (dados.get('variacao_caixa') or 0) / 100
    componentes = []
    for item in dados.get('top_movimentos', [])[:8]:
        valor = item['movimento'] / 100
        componentes.append({
            'id': item['conta'],
            'titulo': item['conta'],
            'valor_centavos': item['movimento'],
        })
    return {
        'titulo': f'Resumo de {comp}',
        'metrica': 'relatorio_mensal',
        'periodicidade': 'mensal',
        'ano': int(comp[:4]) if comp[:4].isdigit() else 2026,
        'formula': 'Receitas - Despesas do mês; caixa acumulado até o fim do mês',
        'unidade': 'centavos',
        'pontos': [{
            'label': comp,
            'valor': resultado * 100,
            'anterior': None,
            'variacao': None,
            'variacao_percentual': None,
            'parcial': False,
            'memoria': {'componentes': componentes},
        }],
        'avisos': [
            f'Receitas: R$ {receitas:,.2f}',
            f'Despesas: R$ {despesas:,.2f}',
            f'Caixa final: R$ {caixa_final:,.2f}',
            f'Variação do caixa no mês: R$ {variacao:,.2f}',
        ] + [f"{d['titulo']}: {d['texto']}" for d in dados.get('destaques', [])],
    }


def _plano_local(dados):
    """Narrativa local: fatos calculados, sem interpretação de causa."""
    comp = dados.get('competencia', '')
    receitas = (dados.get('receitas') or 0) / 100
    despesas = (dados.get('despesas') or 0) / 100
    resultado = (dados.get('resultado') or 0) / 100
    margem = (resultado / receitas * 100) if receitas else 0
    caixa_final = (dados.get('caixa_final') or 0) / 100
    variacao = (dados.get('variacao_caixa') or 0) / 100
    linhas = [f'Resumo de {comp} (calculado pelo app):']
    linhas.append(f'- Receitas: R$ {receitas:,.2f}; Despesas: R$ {despesas:,.2f}; '
                  f'Resultado: R$ {resultado:,.2f} (margem {margem:.1f}%).')
    linhas.append(f'- Caixa e bancos ao fim do mês: R$ {caixa_final:,.2f} '
                  f'({"alta" if variacao >= 0 else "queda"} de R$ {abs(variacao):,.2f} no mês).')
    if dados.get('destaques'):
        linhas.append('- Destaques: ' + ' '.join(d['texto'] for d in dados['destaques'][:3]))
    return '\n'.join(linhas)
