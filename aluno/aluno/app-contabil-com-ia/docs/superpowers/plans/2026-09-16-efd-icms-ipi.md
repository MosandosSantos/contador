# EFD-ICMS/IPI — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gerar a EFD-ICMS/IPI mensal em rascunho a partir da base de NFs existente, com colunas ICMS/IPI nos itens, apuração E110 (ICMS) e E510/E520 (IPI), validador estrutural.

**Architecture:** Mesmo padrão dos ciclos anteriores: `core/efd_icms_ipi.py` (gerador puro), rotas novas em `modules/efd.py` (`/efd-icms-ipi` + `/exportar/efd-icms-ipi`), colunas novas em `nf_itens`, validador por script. Fonte única de `CAMPOS_MINIMOS` no gerador.

**Tech Stack:** Flask 3 + Jinja2 + PostgreSQL (psycopg2); validadores por script.

**Spec:** `docs/superpowers/specs/2026-09-16-efd-icms-ipi-design.md`

---

## Task 1: Schema

- [ ] Acrescentar ao fim de `scripts/schema.sql`:

```sql
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS ncm text NOT NULL DEFAULT '';
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS cst_icms text NOT NULL DEFAULT '';
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_bc_icms_centavos bigint NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS aliq_icms numeric(6,2) NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_icms_centavos bigint NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_bc_ipi_centavos bigint NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS aliq_ipi numeric(6,2) NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_ipi_centavos bigint NOT NULL DEFAULT 0;
```

- [ ] Aplicar com `python "scripts\local.py" --stop; python "scripts\local.py" --start` e conferir colunas via `information_schema.columns`.

## Task 2: Gerador `core/efd_icms_ipi.py`

- [ ] Criar com `calcular(documentos, itens)` (débitos/créditos ICMS e IPI, avisos de CST ausente e divergência bc×aliq) e `gerar(empresa, participantes, documentos, itens, periodo)` emitindo: 0000 (perfil B, 13 campos), 0001, 0100, 0150, 0190, 0200 (com NCM), 0990; B001/B990 e D001/D990, G001/G990, H001/H990, K001/K990, 1001/1990 vazios; C001/C100/C170 (leiaute ICMS com CST_ICMS/CFOP/base/aliq/ICMS/IPI)/C190 (consolidação por CST×CFOP×alíquota)/C990; E100/E110 (aritmética do saldo), E200, E500/E510/E520; bloco 9 idêntico ao da EFD-Contribuições. Constantes: `COD_VER_PADRAO='017'`, `CST_ICMS_VALIDOS`, `CAMPOS_MINIMOS`.
- [ ] Fumaçar com documento de saída CST_ICMS 00, alíquota 18%, ICMS 180 e IPI 10%: asserções E110 e 9999.

## Task 3: Módulo + coleta

- [ ] `modules/efd.py`: `POST /nf/item` grava os campos novos (CST_ICMS em lista válida, NCM 8 dígitos opcional, bases/alíquotas/valores); `GET /efd-icms-ipi` (KPIs + avisos); `GET /exportar/efd-icms-ipi?periodo=`.
- [ ] Nav: NAV ganha `('efd-icms-ipi','EFD ICMS/IPI','ph-tag')`; grupo Fiscal `['ecf','nf','efd-contribuicoes','efd-icms-ipi']`; ROTAS `'efd-icms-ipi':'fiscal'`.

## Task 4: Telas

- [ ] `nf.html`: modal de item com CST_ICMS, NCM, bases/alíquotas/valores de ICMS e IPI; colunas ICMS/IPI na tabela de itens.
- [ ] `efd_icms_ipi.html`: seletor de período, KPIs, consolidações, botão de export.

## Task 5: Validador `scripts/validar_efd_icms_ipi.py`

- [ ] Latin-1, whitelist, contagens 9900/9990/9999, aritmética do E110 (saldo = débitos − créditos; recolher = max(saldo,0); credor = max(−saldo,0)).

## Task 6: E2E + limpeza

- [ ] Restart; e2e Python (urllib) cria participante/documento/itens com ICMS/IPI, exporta, valida (exit 0) e limpa os dados de teste.
