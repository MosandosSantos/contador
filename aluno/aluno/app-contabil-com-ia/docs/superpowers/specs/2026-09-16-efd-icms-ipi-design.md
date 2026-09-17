# Design: EFD-ICMS/IPI — corte essencial

Data: 2026-09-16 · Status: aprovado pelo dono do produto ("vamos pro item 4"); revisão técnica por contador pendente.

## Contexto

4º documento da fila SPED (ECD ✅ → ECF ✅ → EFD-Contribuições ✅ → **EFD-ICMS/IPI** → eSocial). Mensal, para contribuintes de ICMS/IPI. **Reaproveita a base de documentos fiscais** (`nf_documentos`/`nf_itens`) criada no ciclo anterior.

## Escopo

- **Coleta**: `nf_itens` ganha colunas ICMS/IPI (cst_icms, base/alíquota/valor de ICMS e IPI, NCM). Modal de item estendido na tela `/nf`.
- **Geração** (`/exportar/efd-icms-ipi?periodo=`, mensal): bloco 0 (0000 com perfil B, 0100, 0150, 0190, 0200 com NCM), blocos vazios B/D/G/H/K/1, bloco C (C100/C170 no leiaute ICMS + C190 consolidando por CST×CFOP×alíquota), bloco E (E100/E110 apuração ICMS por UF com débitos−créditos, E200 ST, E500/E510/E520 IPI) e bloco 9 com contagens.
- **Cálculo**: débitos (saídas) × créditos (entradas) por CST/CFOP; saldo apurado → ICMS a recolher ou saldo credor; IPI análogo.

## Não-escopo (para o contador)

- ICMS-ST (substituição tributária), CIAP, inventário (H), produção (K), controles do bloco 1, DAV/CT-e (bloco D), ajustes E111–E116.
- COD_VER fixo (`017` padrão) e posicionamento de campos a conferir no leiaute vigente.

## Banco

`ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS`: `ncm`, `cst_icms`, `vl_bc_icms_centavos`, `aliq_icms`, `vl_icms_centavos`, `vl_bc_ipi_centavos`, `aliq_ipi`, `vl_ipi_centavos`.

## Telas / navegação

- `/nf`: modal de item ganha campos ICMS/IPI/NCM; tabela de itens mostra ICMS e IPI.
- Nova `/efd-icms-ipi` (KPIs: ICMS débito/crédito/saldo, IPI a recolher; avisos) + export.
- Nav: Fiscal ganha `efd-icms-ipi`; ROTAS `'efd-icms-ipi':'fiscal'`.

## Verificação

- `scripts/validar_efd_icms_ipi.py`: latin-1, whitelist, contagens do bloco 9 (9900/9990/9999), aritmética interna do E110 (saldo = débitos − créditos; recolher/credor coerentes).
- E2E: documento + itens com ICMS/IPI → export → validar → limpeza.
