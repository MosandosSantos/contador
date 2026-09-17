# Design: ECF Essencial (Lucro Presumido)

Data: 2026-09-16 · Status: aprovado pelo dono do produto; revisão técnica por contador pendente.

## Contexto

O app já exporta a ECD (Escrituração Contábil Digital) em rascunho via `core/ecd.py` + rota `/exportar/ecd`. Foi aprovado implementar os 4 documentos SPED que faltam, um por vez, com coleta de dados dentro do app. O primeiro é a **ECF (Escrituração Contábil Fiscal)**, anual, obrigatória para PJ tributada por Lucro Real/Presumido/Arbitrado.

## Escopo e não-escopo

**Escopo (corte essencial — Lucro Presumido):**
- Blocos: 0 (0000, 0001, 0010, 0020, 0030, 0035, 0450), J (J005, J030), M (M300, M310, M410, M415, M500), N (N600, N630, N650, N660, N670), Y (Y180, Y520, Y540, Y550, Y640, Y650, Y660, Y671, Y680, Y690, Y980, Y990), 9999.
- Coleta de dados por telas do app (ver §3) e cálculo de IRPJ/CSLL presumido pelo app (ver §4).

**Não-escopo desta fase (documentado para o contador):**
- Blocos de Lucro Real (L, K, livro AP), blocos X/U/Q (certificados, lucro da exploração, eventos corporativos).
- Regime Simples (não entrega ECF — o app avisa e bloqueia).
- Assinatura digital, transmissão ou validação oficial no PVA da Receita: o arquivo é **rascunho** para conferência do contador, como a ECD.

## 1. Banco de dados (scripts/schema.sql, padrão `IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS`)

- `empresa`: `ADD COLUMN ie text NOT NULL DEFAULT ''`, `cod_mun text NOT NULL DEFAULT ''` (IBGE 7 dígitos). `regime` passa a validar valores `real|presumido|arbitrado|simples` (simples → aviso na exportação).
- `participantes`: `ADD COLUMN ie text NOT NULL DEFAULT ''`, `uf text NOT NULL DEFAULT ''`, `cod_mun text NOT NULL DEFAULT ''` → registro 0035.
- `ecf_parametros` (PK: `ano`): `ano integer`, `forma_tributacao text CHECK IN ('trimestral','mensal_estimativa')`, `pct_presuncao_irpj numeric`, `pct_presuncao_csll numeric`, `adicional boolean NOT NULL DEFAULT true`, `atualizado timestamptz`.
- `ecf_contas_pb` (PK: `codigo`): `codigo text`, `descricao text`, `tipo text CHECK IN ('A','B')` → M410/M415.
- `ecf_lancamentos` (PK: `id serial`): `periodo text` (`AAAAT` ou `AAAAMM`), `conta_pb text REFERENCES ecf_contas_pb(codigo)`, `tipo text CHECK IN ('A','B','C')` (adição/exclusão/compensação), `data date`, `valor_centavos bigint`, `historico text` → M300/M310.
- `ecf_conciliacao` (PK: `id serial`): `conta_id text` (conta contábil), `historico text`, `valor_centavos bigint` (sinal: adição +/exclusão −), `ordem integer` → Y680.
- Auditoria: toda gravação nas tabelas novas escreve em `auditoria` (padrão do app).

## 2. Rotas (modules/ecf.py, blueprint novo)

- `GET /ecf` — tela única com 3 seções (ver §3). Contexto: parâmetros do ano, listas de contas Parte B, lançamentos, conciliação, totais calculados e avisos de completude.
- `POST /ecf/parametros` — grava `ecf_parametros` (via `resposta_edicao`).
- `POST /ecf/conta-pb` — cria/edita conta Parte B; `POST /ecf/conta-pb/<codigo>/remover`.
- `POST /ecf/lancamento` — cria/edita lançamento Parte B; `POST /ecf/lancamento/<id>/remover`.
- `POST /ecf/conciliacao` — cria/edita item de conciliação; `POST /ecf/conciliacao/<id>/remover`.
- `GET /exportar/ecf` — gera o arquivo (latin-1, CRLF) + avisos em flash; espelha `exportar_ecd` em `modules/cadastros.py`.
- Todos com `@login_required`, CSRF (padrão `core/security.py`) e validação `ValueError → resposta_edicao(..., erro=True)`.

## 3. Telas (templates + CSS existentes)

- **`/empresa`** e **`/participantes`**: campos novos nos modais existentes (padrão `modal_edicao.html` + `modal-edicao.js`).
- **`templates/ecf.html`** (extende `base.html`): 3 seções em cards —
  1. **Parâmetros do ano** (form inline): ano, forma de tributação, % presunção IRPJ/CSLL, adicional.
  2. **Lançamentos na apuração (Parte B)**: tabela avançada (`data-table-advanced`) + modals de criação/edição.
  3. **Conciliação contábil × fiscal (Y680)**: idem.
  - Botão de destaque **"Gerar arquivo ECF"** (`top_actions`) + lista de pendências de completude (ex.: "12 contas analíticas sem referencial", "CNPJ ausente").
- **Navegação**: grupo novo **Fiscal** em `MENU_GRUPOS` (`modules/pages.py`) com item `ecf`; `config/modulos.json` ganha `ecf` em `habilitados`; `NAV` ganha `{slug:'ecf'}`.
- CSS próprio `static/css/ecf.css` só se o layout padrão não bastar (meta: reusar componentes).

## 4. Cálculo (core/ecf.py — gerador; core/igual estilo do ecd.py)

`gerar_ecf(empresa, contas, mov, participantes, parametros, contas_pb, lancamentos_pb, conciliacao, ano) -> (texto, avisos)`

Derivado dos lançamentos existentes:
- **Receita bruta do ano**: soma dos créditos de contas analíticas com `grupo='resultado'` e `linha_dre='receita_bruta'` (classificação já usada pela DRE de referência em `core/calculos.py`). Deduções (`linha_dre='deducoes'`) reduzem a receita líquida de Y520/Y540.
- **Lucro contábil (Y180)**: resultado das contas de `grupo='resultado'` no ano-calendário.
- **Balancetes J005/J030**: mesma agregação do J100 da ECD, recortada no ano.
- **IRPJ presumido**: base = receita bruta × `pct_presuncao_irpj` (por trimestre/mês conforme forma de tributação); IRPJ = base × 15%; adicional de 10% sobre a base que exceder R$ 60.000 por trimestre (quando `adicional=true`).
- **CSLL presumida**: base = receita bruta × `pct_presuncao_csll`; CSLL = base × 9%.
- **Y680**: lucro contábil (Y180) + itens informados em `ecf_conciliacao` = lucro fiscal; diferença contra a soma da Parte B gera aviso.

Informado pelo usuário: parâmetros, contas Parte B, lançamentos Parte B, conciliação.

Avisos (padrão ECD): CNPJ/IE/COD_MUN ausentes, regime `simples`, receita zerada, base de cálculo divergente da soma da Parte B, contas sem referencial (0450), documento desequilibrado.

## 5. Verificação

- **`scripts/validar_ecf.py`** (espelho do `validar_ecd.py`): gera ECF da base demo/sintética, valida sequência de blocos, contagem de registros do 9999, soma dos J030, fechamento Y680 e codificação latin-1. Falha com exit code ≠ 0.
- **Fluxo no app**: empresa completa → `/ecf` com parâmetros + 1 lançamento Parte B + 1 conciliação → `/exportar/ecf` → validar_ecf no arquivo baixado.
- Nenhum teste automatizado formal existe no projeto; mantém-se o padrão de validadores por script.

## 6. Decisões abertas para o revisor (contador)

1. Percentuais de presunção padrão sugeridos na tela (comércio 8%/12%, serviços 32%/32%) — legenda de ajuda, não validação dura.
2. Layout de referência: leiaute ECF vigente do ano-calendário (COD_VER). O gerador usa versão fixa parametrizável (`COD_VER`) para o contador ajustar por ano.
3. Apuração "mensal_estimativa" simplificada: gera K-codes? Não — nesta fase os N-registros saem trimestralizados quando `forma_tributacao='trimestral'`; estimativa mensal entra como trimestres agregados + aviso para conferência.
