# Design: eSocial — corte essencial

Data: 2026-09-16 · Status: aprovado pelo dono do produto ("siga para o esocial"); revisão técnica por contador pendente.

## Contexto

5º e último documento da fila SPED. **eSocial não é arquivo texto de barras**: é um sistema de eventos XML transmitidos individualmente por web service. A entrega coerente com o padrão do app é a coleta dos dados trabalhistas dentro do app e a geração de um **ZIP de XMLs rascunho** dos eventos essenciais, conferíveis no validador oficial (AVS) — com `tpAmb=2` (produção restrita), sem assinatura.

## Escopo

- **Coleta** (tela `/esocial`, 4 seções):
  1. Parâmetros do empregador (S-1000): classificação tributária, natureza jurídica, indicativo de desoneração.
  2. **Empregados**: nome, CPF (com dígito verificador), NIS, cargo, CBO, data de admissão, salário, ativo.
  3. **Rubricas** (S-1010): código, descrição, tipo (provento/desconto), incidência INSS/IRRF.
  4. **Folha mensal**: lançamentos empregado × rubrica × período (AAAA-MM) com valor; consolidação de bases (INSS, IRRF, FGTS) pelas flags de incidência.
- **Geração** (`/exportar/esocial?periodo=`): ZIP com `S1000.xml` (evtInfoEmpregador), `S1010.xml` (evtTabRubrica), `S2200_<id>.xml` (evtAdmissao por empregado), `S1200_<periodo>.xml` (evtRemun consolidado — nota: transmissão oficial exige um evento por trabalhador), `S1299_<periodo>.xml` (evtFechaEvPer com totais).

## Não-escopo (para o contador)

- Assinatura digital, transmissão, distribuição (DFe), eventos não essenciais (S-1210 pagamentos, S-1280, S-1298, SST S-2200+ compl., folha 13º/anual S-1210/1300 etc.).
- Cálculo de INSS/IRRF/FGTS: o app **consolida bases pelas flags** e expõe totais; o valor efetivo das contribuições continua responsabilidade do contador (rascunho).
- Versões de leiaute do XML (namespace v02_04_02 fixo; conferir vigente).

## Banco

- `esocial_parametros` (singleton id=1): clas_tribut, nat_juridica, ind_deson.
- `esocial_empregados`: nome, cpf (UNIQUE, validado), nis, cargo, cbo, data_admissao, salario_centavos, ativo.
- `esocial_rubricas`: codigo (UNIQUE), descricao, tipo (`provento|desconto`), incid_inss, incid_irrf.
- `esocial_folha`: periodo (`AAAA-MM`), empregado_id (CASCADE), rubrica_id, valor_centavos; UNIQUE(periodo,empregado_id,rubrica_id).

## Navegação

Grupo Fiscal ganha `esocial`; ROTAS `'esocial':'fiscal'` (módulo já habilitado).

## Verificação

- `scripts/validar_esocial.py <zip>`: membros esperados presentes; XML parseável com o evento certo; CNPJ do empregador coerente; CPFs válidos; Σ valores do S-1200 = totais do S-1299.
- E2E: parametriza → empregado (CPF válido calculado) → rubrica → folha → export ZIP → validar → limpeza.
