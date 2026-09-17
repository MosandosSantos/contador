# EFD-Contribuições (PIS/COFINS) — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coletar documentos fiscais com itens (PIS/COFINS por CST) e gerar a EFD-Contribuições mensal em rascunho, com validador estrutural.

**Architecture:** Mesmos padrões do ciclo ECF: gerador puro em `core/efd_contribuicoes.py` (`calcular()` + `gerar()`), blueprint `modules/efd.py` (telas `/nf` e `/efd-contribuicoes`, export `/exportar/efd-contribuicoes`), schema idempotente, validador por script. Base de NFs reutilizável pelo EFD-ICMS/IPI.

**Tech Stack:** Flask 3 + Jinja2 + PostgreSQL (psycopg2); validadores por script (padrão do projeto).

**Spec:** `docs/superpowers/specs/2026-09-16-efd-contribuicoes-design.md`

---

## Task 1: Schema — nf_documentos + nf_itens

- [ ] **Step 1: Acrescentar ao fim de `scripts/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS nf_documentos (
 id bigserial PRIMARY KEY,
 periodo text NOT NULL CHECK(periodo ~ '^20[0-9]{2}-(0[1-9]|1[0-2])$'),
 tipo text NOT NULL CHECK(tipo IN ('saida','entrada','servico')),
 participante text NOT NULL REFERENCES participantes(chave),
 numero text NOT NULL DEFAULT '', serie text NOT NULL DEFAULT '',
 data_emissao date NOT NULL,
 valor_total_centavos bigint NOT NULL DEFAULT 0,
 atualizado timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(periodo,tipo,participante,numero,serie)
);
CREATE INDEX IF NOT EXISTS nf_documentos_periodo ON nf_documentos(periodo);
CREATE TABLE IF NOT EXISTS nf_itens (
 id bigserial PRIMARY KEY,
 documento_id bigint NOT NULL REFERENCES nf_documentos(id) ON DELETE CASCADE,
 descricao text NOT NULL,
 cst_pis text NOT NULL DEFAULT '', cst_cofins text NOT NULL DEFAULT '',
 cfop text NOT NULL DEFAULT '',
 vl_item_centavos bigint NOT NULL DEFAULT 0,
 vl_bc_pis_centavos bigint NOT NULL DEFAULT 0, aliq_pis numeric(6,2) NOT NULL DEFAULT 0, vl_pis_centavos bigint NOT NULL DEFAULT 0,
 vl_bc_cofins_centavos bigint NOT NULL DEFAULT 0, aliq_cofins numeric(6,2) NOT NULL DEFAULT 0, vl_cofins_centavos bigint NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS nf_itens_documento ON nf_itens(documento_id);
```

- [ ] **Step 2: Aplicar (stop/start roda preparar.py)**

```powershell
python "scripts\local.py" --stop; if ($?) { python "scripts\local.py" --start }
```

Verificação: script temporário consulta `information_schema.tables` para `nf_%`.

---

## Task 2: Gerador — `core/efd_contribuicoes.py`

- [x] **Step 1: Escrever o módulo completo** — implementado em `core/efd_contribuicoes.py`: `calcular(documentos, itens) -> dict` consolida por CST com conferência `bc×aliq ≈ contribuição` (3 avisos no máximo); `gerar(empresa, participantes, documentos, itens, periodo) -> (texto, avisos)` emite blocos 0 (0000/0001/0100/0110/0150/0190/0200/0990), A (A001/A100/A170/A990), C (C001/C100/C170/C990), F vazio (F001/F990), M (M001/M100/M200/M500/M600/M990), 1 (1001/1990), 9 (9001/9900/9990/9999) com contagens calculadas. Constantes: `COD_VER_PADRAO='0030'`, `CSTS_VALIDOS`, `CAMPOS_MINIMOS` (fonte única compartilhada com o validador).

- [x] **Step 2: Fumaçar com dados sintéticos** — OK: documento de saída R$ 1.000,00, item CST 01, PIS 1,65% (R$ 16,50), COFINS 7,6% (R$ 76,00): `|M100|01|0|1650|0|0|`, `|M200|1650|1650|…`, `|M500|01|0|7600|0|0|`, `|M600|7600|7600|…`, 55 linhas, 9999 coerente.

## Task 3: Blueprint — `modules/efd.py` + registro

- [ ] **Step 1: Criar `modules/efd.py`** — rotas: `GET /nf` (lista por período + itens de `?doc=`), `POST /nf/doc`, `POST /nf/doc/<id>/remover`, `POST /nf/item`, `POST /nf/item/<id>/remover`, `GET /efd-contribuicoes` (KPIs + avisos), `GET /exportar/efd-contribuicoes?periodo=`. CSRF, `resposta_edicao`, advisory lock próprio (20260924), auditoria em toda gravação.

- [ ] **Step 2: Registrar** — `app.py` importa e registra; `modules/pages.py` NAV ganha `nf` e `efd-contribuicoes`; grupo Fiscal: `['ecf','nf','efd-contribuicoes']`; `core/modulos.py` ROTAS: `'nf':'fiscal', 'efd-contribuicoes':'fiscal'` (módulo `fiscal` já habilitado).

- [ ] **Step 3: Verificar** — `python -m py_compile` nos arquivos.

## Task 4: Telas — `templates/nf.html` e `templates/efd_contribuicoes.html`

- [ ] **Step 1: nf.html** — seletor de período, tabela de documentos (tipo, participante, número, data, total informado × Σ itens com destaque de divergência, ações Itens/Editar/Remover), seção de itens do documento selecionado (`?doc=`), modals de documento e item (CSTs da lista oficial, CFOP 4 dígitos).
- [ ] **Step 2: efd_contribuicoes.html** — seletor de período, KPIs (documentos, itens, PIS, COFINS), lista de avisos, botão "Gerar arquivo EFD-Contribuições".

## Task 5: Validador — `scripts/validar_efd_contribuicoes.py`

- [ ] **Step 1: Criar** — confere latin-1, pipes, whitelist `CAMPOS_MINIMOS`, 0000 primeiro/9999 último, contagens declaradas no 9900 × reais, 9990 = linhas do bloco 9, 9999 = total, M200 = ΣM100 (campo 3) e M600 = ΣM500.
- [ ] **Step 2: Compilar.**

## Task 6: E2E + limpeza

- [ ] **Step 1: Restart.** **Step 2:** script Python (urllib, cookiejar, CSRF renovado pós-login) cria participante de teste com CNPJ válido calculado, documento, 2 itens, exporta. **Step 3:** `python scripts/validar_efd_contribuicoes.py <arquivo>` exit 0. **Step 4:** limpar nf_itens/nf_documentos/participante de teste.
