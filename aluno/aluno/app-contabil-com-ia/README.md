# APP CONTÁBIL COM IA

Aplicativo Flask/PostgreSQL do workshop. A instalação começa vazia: nenhum lançamento, orçamento, conciliação ou chave de IA vem carregado.

## Abrir no Windows

1. Em uma máquina nova, instale Python 3.10+ e PostgreSQL 16. O serviço PostgreSQL do Windows não precisa estar iniciado.
2. Rode `preparar_ambiente.bat` uma vez; ele cria `.venv` e baixa as dependências Python.
3. Rode `iniciar.bat`. O controlador cria um cluster PostgreSQL exclusivo em `.runtime`, escolhe portas livres e abre o navegador.
4. Entre com `teste@teste.com` e senha `teste`. A página inicial é **Início**. Na primeira entrega, abra **Conciliar → Enviar relatórios** e carregue os dois XLSX. Importar e os demais módulos aparecem após serem pedidos.
5. Rode `parar.bat` para encerrar apenas a instância que este projeto iniciou. Para abrir novamente, rode `iniciar.bat`.

O modelo baixado em Importar é sintético e serve para mostrar o formato do arquivo. As bases do aluno não acompanham este pacote.

## IA

A análise abre sem chave. Em **Configuração da IA**, a pessoa pode informar a própria chave, escolher um modelo, testar e salvar. O teste não leva números da empresa. Disponibilidade, limite, custo, idioma e tempo de resposta dependem da conta e precisam ser ensaiados antes da aula.

## Docker

O `Dockerfile` prepara o schema ao iniciar. Use PostgreSQL separado e forneça `DATABASE_URL`, `SECRET_KEY` com pelo menos 32 caracteres aleatórios, `APP_ENV=production` e `PORT`. Faça build e teste no destino antes de qualquer publicação; este pacote não publica nem carrega banco, runtime ou segredos.

## Acrescentar etapas na mesma aplicação

Feche o app com `parar.bat`. Baixe o ZIP da nova versão (não precisa extrair). Na pasta do app, dê dois cliques em `atualizar.bat` e escolha o ZIP baixado. A ponte preserva banco, configuração, chave e anexos e aplica as fontes. Depois, abra `iniciar.bat` para usar. Se houver conflito, nenhum arquivo é atualizado.

As seções sobre Importar, IA e Docker acima se aplicam quando esses módulos forem acrescentados. A etapa `publicacao` inclui o Dockerfile e o guia de publicação.
