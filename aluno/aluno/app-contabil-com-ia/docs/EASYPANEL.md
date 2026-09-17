# Caminho Docker/EasyPanel

Este pacote contém o código necessário ao build: `Dockerfile`, `app.py`, `core/`, `modules/`, `templates/`, `static/`, `dados/`, `scripts/schema.sql`, `scripts/preparar.py` e `requirements.txt`. O banco fica fora da imagem.

Crie PostgreSQL separado e depois um serviço de App com builder Dockerfile e caminho `Dockerfile`. Configure a conexão interna do banco e:

```text
APP_ENV=production
DATABASE_URL=postgresql://USUARIO:SENHA@HOST_INTERNO:5432/BANCO
SECRET_KEY=UMA_CHAVE_ALEATORIA_DE_PELO_MENOS_32_CARACTERES
PORT=8080
```

Não coloque segredos no Dockerfile, ZIP ou argumentos de build. A imagem prepara o schema e inicia Gunicorn na porta interna 8080. Valide `/health`, login, importação e demonstrativos no destino de ensaio antes de publicar. O código não é backup do banco: exporte e restaure PostgreSQL separadamente quando houver dados a preservar.
