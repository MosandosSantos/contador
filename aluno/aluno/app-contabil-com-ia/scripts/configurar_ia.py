"""Atalho para o fluxo único de configuração: escolher, testar e salvar no app."""
import json
import webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    try:
        state=json.loads((ROOT/'.runtime/estado.json').read_text(encoding='utf-8'))
        url=state.get('url','')
    except (OSError,ValueError,TypeError):
        url=''
    if not isinstance(url,str) or not url.startswith('http://127.0.0.1:'):
        print('Abra o app com iniciar.bat antes de configurar.')
        return 1
    url=url.rstrip('/') + '/configuracao-ia'
    print('Na tela: gere sua chave, escolha o modelo, teste e depois salve.')
    print(url)
    webbrowser.open(url)
    return 0

if __name__=='__main__': raise SystemExit(main())
