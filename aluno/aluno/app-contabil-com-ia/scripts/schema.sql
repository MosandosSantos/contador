CREATE TABLE IF NOT EXISTS usuarios (
 email text PRIMARY KEY, senha_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS contas (
 conta_id text PRIMARY KEY, descricao text NOT NULL, grupo text NOT NULL,
 componente text, linha_dre text, analitica boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS lancamentos (
 linha_id text PRIMARY KEY, documento_id text NOT NULL, empresa_id text NOT NULL,
 data date NOT NULL, conta_id text NOT NULL REFERENCES contas,
 debito_centavos bigint NOT NULL CHECK(debito_centavos>=0),
 credito_centavos bigint NOT NULL CHECK(credito_centavos>=0),
 tipo text NOT NULL, historico text NOT NULL, origem_id text NOT NULL,
 centro_id text NOT NULL DEFAULT '', atividade_caixa text NOT NULL DEFAULT '', rubrica_caixa text NOT NULL DEFAULT '',
 CHECK(debito_centavos=0 OR credito_centavos=0)
);
CREATE INDEX IF NOT EXISTS lancamentos_data ON lancamentos(data,conta_id);
CREATE TABLE IF NOT EXISTS orcamento (
 competencia text NOT NULL, conta_id text NOT NULL REFERENCES contas,
 valor_dc_centavos bigint NOT NULL, PRIMARY KEY(competencia,conta_id)
);
CREATE TABLE IF NOT EXISTS reclassificacoes (
 competencia text NOT NULL, conta_id text NOT NULL REFERENCES contas,
 destino text NOT NULL CHECK(destino IN ('estrutura','custos_servicos')),
 PRIMARY KEY(competencia,conta_id)
);
CREATE TABLE IF NOT EXISTS auditoria (
 id bigserial PRIMARY KEY, data timestamptz NOT NULL DEFAULT now(),
 acao text NOT NULL, antes jsonb NOT NULL, depois jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS conciliacao (
 id integer PRIMARY KEY CHECK(id=1), extrato jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS login_tentativas (
 ip text PRIMARY KEY, quantidade integer NOT NULL DEFAULT 0, atualizado timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS versoes_schema (versao integer PRIMARY KEY, aplicada timestamptz NOT NULL DEFAULT now());
ALTER TABLE contas ADD COLUMN IF NOT EXISTS conta_pai_id text NOT NULL DEFAULT '';
ALTER TABLE contas ADD COLUMN IF NOT EXISTS ordem integer NOT NULL DEFAULT 100;
ALTER TABLE contas ADD COLUMN IF NOT EXISTS nivel integer NOT NULL DEFAULT 1;
ALTER TABLE contas ADD COLUMN IF NOT EXISTS natureza text NOT NULL DEFAULT '';
ALTER TABLE contas ADD COLUMN IF NOT EXISTS cod_referencial text NOT NULL DEFAULT '';
ALTER TABLE contas ADD COLUMN IF NOT EXISTS classe_bp text NOT NULL DEFAULT 'pendente';
CREATE TABLE IF NOT EXISTS centros (centro_id text PRIMARY KEY,descricao text NOT NULL);
CREATE TABLE IF NOT EXISTS regras_centros (
 id bigserial PRIMARY KEY,conta_id text NOT NULL DEFAULT '',
 centro_origem text NOT NULL,centro_destino text NOT NULL REFERENCES centros,
 inicio date NOT NULL,fim date NOT NULL,prioridade integer UNIQUE NOT NULL,
 justificativa text NOT NULL,CHECK(inicio<=fim)
);
CREATE TABLE IF NOT EXISTS dre_grupos (
 codigo text PRIMARY KEY,nome text NOT NULL,ordem integer UNIQUE NOT NULL,
 tipo text NOT NULL CHECK(tipo IN ('detalhe','subtotal'))
);
CREATE TABLE IF NOT EXISTS dre_vinculos (
 conta_id text NOT NULL REFERENCES contas,centro_id text NOT NULL DEFAULT '',
 grupo_codigo text NOT NULL REFERENCES dre_grupos,PRIMARY KEY(conta_id,centro_id)
);
CREATE TABLE IF NOT EXISTS dre_contas_config (
 conta_id text PRIMARY KEY REFERENCES contas ON DELETE CASCADE,
 modo text NOT NULL CHECK(modo IN ('linha','centro')),
 grupo_codigo text REFERENCES dre_grupos,
 CHECK(modo='linha' OR grupo_codigo IS NULL)
);
CREATE TABLE IF NOT EXISTS dre_centros_config (
 centro_id text PRIMARY KEY REFERENCES centros ON DELETE CASCADE,
 grupo_codigo text REFERENCES dre_grupos
);
CREATE TABLE IF NOT EXISTS importacoes_previa (
 token text PRIMARY KEY,criada timestamptz NOT NULL DEFAULT now(),
 arquivo text NOT NULL,conteudo jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS bases_arquivadas (
 id bigserial PRIMARY KEY,criada timestamptz NOT NULL DEFAULT now(),
 motivo text NOT NULL,conteudo jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS preferencias_ui (
 email text NOT NULL REFERENCES usuarios(email),chave text NOT NULL,
 valor jsonb NOT NULL DEFAULT '{}'::jsonb,PRIMARY KEY(email,chave)
);
CREATE TABLE IF NOT EXISTS conciliacoes_titulos (
 id integer PRIMARY KEY CHECK(id=1), arquivos jsonb NOT NULL,
 resultado jsonb NOT NULL, atualizado timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS configuracoes_ia (
 id integer PRIMARY KEY CHECK(id=1),chave text NOT NULL,modelo text NOT NULL,
 atualizado timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS admin boolean NOT NULL DEFAULT false;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS criado_por text NOT NULL DEFAULT '';
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS criado timestamptz NOT NULL DEFAULT now();
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS atualizado timestamptz NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS empresa (
 id integer PRIMARY KEY CHECK(id=1),cnpj text NOT NULL,razao_social text NOT NULL,
 nome_fantasia text NOT NULL DEFAULT '',regime text NOT NULL,
 cep text NOT NULL DEFAULT '',logradouro text NOT NULL DEFAULT '',numero text NOT NULL DEFAULT '',
 complemento text NOT NULL DEFAULT '',bairro text NOT NULL DEFAULT '',municipio text NOT NULL DEFAULT '',
 uf text NOT NULL DEFAULT '',atualizado timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS participantes (
 chave text PRIMARY KEY,documento text NOT NULL DEFAULT '',nome text NOT NULL,
 tipo text NOT NULL CHECK(tipo IN ('cliente','fornecedor','ambos')),
 criado timestamptz NOT NULL DEFAULT now(),atualizado timestamptz NOT NULL DEFAULT clock_timestamp()
);

ALTER TABLE empresa ADD COLUMN IF NOT EXISTS ie text NOT NULL DEFAULT '';
ALTER TABLE empresa ADD COLUMN IF NOT EXISTS cod_mun text NOT NULL DEFAULT '';
ALTER TABLE participantes ADD COLUMN IF NOT EXISTS ie text NOT NULL DEFAULT '';
ALTER TABLE participantes ADD COLUMN IF NOT EXISTS uf text NOT NULL DEFAULT '';
ALTER TABLE participantes ADD COLUMN IF NOT EXISTS cod_mun text NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS ecf_parametros (
 ano integer PRIMARY KEY CHECK(ano BETWEEN 2000 AND 2100),
 forma_tributacao text NOT NULL CHECK(forma_tributacao IN ('trimestral','mensal_estimativa')),
 pct_presuncao_irpj numeric(5,2) NOT NULL CHECK(pct_presuncao_irpj BETWEEN 0 AND 100),
 pct_presuncao_csll numeric(5,2) NOT NULL CHECK(pct_presuncao_csll BETWEEN 0 AND 100),
 adicional boolean NOT NULL DEFAULT true,
 atualizado timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ecf_contas_pb (
 codigo text PRIMARY KEY, descricao text NOT NULL, tipo text NOT NULL CHECK(tipo IN ('A','B'))
);
CREATE TABLE IF NOT EXISTS ecf_lancamentos (
 id bigserial PRIMARY KEY, periodo text NOT NULL CHECK(periodo ~ '^20[0-9]{2}T[1-4]$'),
 conta_pb text NOT NULL REFERENCES ecf_contas_pb(codigo),
 tipo text NOT NULL CHECK(tipo IN ('A','B','C')), data date NOT NULL,
 valor_centavos bigint NOT NULL, historico text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ecf_lancamentos_periodo ON ecf_lancamentos(periodo);
CREATE TABLE IF NOT EXISTS ecf_conciliacao (
 id bigserial PRIMARY KEY, conta_id text NOT NULL REFERENCES contas,
 valor_centavos bigint NOT NULL, historico text NOT NULL DEFAULT '', ordem integer NOT NULL DEFAULT 100
);

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

ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS ncm text NOT NULL DEFAULT '';
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS cst_icms text NOT NULL DEFAULT '';
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_bc_icms_centavos bigint NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS aliq_icms numeric(6,2) NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_icms_centavos bigint NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_bc_ipi_centavos bigint NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS aliq_ipi numeric(6,2) NOT NULL DEFAULT 0;
ALTER TABLE nf_itens ADD COLUMN IF NOT EXISTS vl_ipi_centavos bigint NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS esocial_parametros (
 id integer PRIMARY KEY CHECK(id=1),
 clas_tribut text NOT NULL DEFAULT '',
 nat_juridica text NOT NULL DEFAULT '',
 ind_deson text NOT NULL DEFAULT '0',
 atualizado timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS esocial_empregados (
 id bigserial PRIMARY KEY,
 nome text NOT NULL, cpf text NOT NULL UNIQUE, nis text NOT NULL DEFAULT '',
 cargo text NOT NULL DEFAULT '', cbo text NOT NULL DEFAULT '',
 data_admissao date NOT NULL, salario_centavos bigint NOT NULL DEFAULT 0,
 ativo boolean NOT NULL DEFAULT true,
 atualizado timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS esocial_rubricas (
 id bigserial PRIMARY KEY,
 codigo text NOT NULL UNIQUE, descricao text NOT NULL,
 tipo text NOT NULL CHECK(tipo IN ('provento','desconto')),
 incid_inss boolean NOT NULL DEFAULT false, incid_irrf boolean NOT NULL DEFAULT false,
 atualizado timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS esocial_folha (
 id bigserial PRIMARY KEY,
 periodo text NOT NULL CHECK(periodo ~ '^20[0-9]{2}-(0[1-9]|1[0-2])$'),
 empregado_id bigint NOT NULL REFERENCES esocial_empregados(id) ON DELETE CASCADE,
 rubrica_id bigint NOT NULL REFERENCES esocial_rubricas(id),
 valor_centavos bigint NOT NULL,
 UNIQUE(periodo,empregado_id,rubrica_id)
);
CREATE INDEX IF NOT EXISTS esocial_folha_periodo ON esocial_folha(periodo);
