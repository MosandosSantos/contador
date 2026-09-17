"""Sugestões iniciais; a tela também consulta o catálogo vivo e aceita ID manual."""
MODELO_PADRAO = 'nvidia/nemotron-3-super-120b-a12b'
MODELOS = (
    {'id': 'nvidia/nemotron-3.5-lightning-30b-a3b', 'nome': 'NVIDIA Nemotron 3.5 Lightning',
     'descricao': 'Modelo compacto para comparar. Teste o tempo de resposta no seu acesso antes de usar na aula.',
     'url': 'https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b'},
    {'id': 'nvidia/nemotron-3-super-120b-a12b', 'nome': 'NVIDIA Nemotron 3 Super',
     'descricao': 'Recomendado para começar: respondeu ao teste deste app. O app calcula os indicadores; o modelo interpreta a pergunta e explica os resultados. Teste com a sua chave.',
     'url': 'https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b'},
)

MODELOS = tuple(sorted(MODELOS, key=lambda m: m["id"] != MODELO_PADRAO))
