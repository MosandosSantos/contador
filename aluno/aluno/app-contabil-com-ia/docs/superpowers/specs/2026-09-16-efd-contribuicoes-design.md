# Design: EFD-Contribuições (PIS/COFINS) — corte essencial

Data: 2026-09-16 · Status: aprovado pelo dono do produto ("vá em frente"); revisão técnica por contador pendente.

## Contexto

2º documento da fila SPED (ECD ✅ → **EFD-Contribuições** → EFD-ICMS/IPI → eSocial). Aplicável a Lucro Real e Presumido (Simples não entrega). Mensal. A base de documentos fiscais criada aqui será reutilizada pelo EFD-ICMS/IPI no próximo ciclo.

## Escopo

- **Coleta**: documentos fiscais com itens (tela `/nf`): tipo (saída/entrada/serviço), participante, número/série, data, valor; itens com CST-PIS/CST-COFINS, CFOP, base, alíquota e valores de PIS/COFINS.
- **Geração** (`/exportar/efd-contribuicoes`, mensal): blocos 0 (0000/0001/0100/0110/0150/0190/0200), C (C100/C170), A (A100/A170), M (M100/M105?/M200 PIS, M500/M600 COFINS) e Bloco 9 (0990/9900/9990/9999) com contagens honestas.
- **Cálculo**: consolidação por CST (Σ bases, Σ contribuições) para M200/M600; conferência bc×aliq ≈ contribuição gera aviso.

## Não-escopo (documentado para o contador)

- Importação XLSX de documentos/itens (manual via modals na primeira versão).
- Blocos D (CT-e), I, J, P, R, T, 1 (registro analíticos opcionais/avulsos), retificações (IND_SIT ≠ 0).
- Assinatura/transmissão; COD_VER fixo (conferir vigência por ano) — constante no módulo.

## Banco

- `nf_documentos`: id, periodo (`AAAA-MM`), tipo (`saida|entrada|servico`), participante → participantes(chave), numero, serie, data_emissao, valor_total_centavos; UNIQUE(periodo,tipo,participante,numero,serie).
- `nf_itens`: id, documento_id → nf_documentos ON DELETE CASCADE, descricao, cst_pis, cst_cofins, cfop, vl_item/bc/aliq/valor para PIS e COFINS (centavos; alíquotas numeric).
- Participantes já têm IE/UF/COD_MUN (tarefa ECF) → 0150.

## Telas

- `/nf` — lista do período (?periodo=AAAA-MM), modals de documento; seleção `?doc=ID` mostra itens do documento com modal próprio.
- `/efd-contribuicoes` — KPIs do mês (PIS, COFINS, documentos, divergências) + botão de exportação + seletor de período.
- Nav: grupo **Fiscal** ganha `nf` e `efd-contribuicoes`; ROTAS mapeiam ambos para o módulo `fiscal` (já habilitado em modulos.json).

## Verificação

- `scripts/validar_efd_contribuicoes.py`: latin-1, whitelist de registros, contagem do 9999, coerência das contagens do 9900, M200 = ΣM100 e M600 = ΣM500.
- E2E HTTP: documento + itens → exportar → validar. Dados de teste removidos ao final.

## Decisões abertas para o revisor (contador)

1. COD_VER padrão fixo em `core/efd_contribuicoes.py` — conferir valor vigente do mês/ano de referência.
2. Posicionamento exato dos campos PIS/COFINS no C170/A170 segue o corte essencial; conferir leiaute oficial.
3. CSTs aceitos no cadastro: lista completa 01–99 do CST das contribuições; itens "sem CST" são rejeitados (obrigatórios para M100/M500).
