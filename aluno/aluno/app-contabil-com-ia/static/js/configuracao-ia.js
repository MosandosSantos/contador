(() => {
  const button = document.querySelector('[data-ia-test]');
  if (!button) return;
  const form = document.getElementById('configuracao-ia');
  const result = document.querySelector('[data-ia-result]');
  const save = document.querySelector('[data-ia-save]');
  const receipt = form.elements.teste_token;
  const model = form.elements.modelo;
  const key = form.elements.chave;
  const manual = form.elements.modelo_manual;
  const manualBox = document.querySelector('[data-ia-manual]');
  const loadModels = document.querySelector('[data-ia-load-models]');
  const catalogStatus = document.querySelector('[data-ia-catalog-status]');
  const suggestions = Array.from(model.options).filter(o => o.dataset.descricao).map(o => ({
    id: o.value, label: o.textContent, description: o.dataset.descricao, url: o.dataset.url || ''
  }));
  let keyRevision = 0;
  let revision = 0;
  let expiration;
  function invalidate() {
    revision++;
    receipt.value = '';
    save.disabled = true;
    clearTimeout(expiration);
    result.removeAttribute('data-ok');
    result.textContent = 'Teste a chave e o modelo escolhidos antes de salvar.';
  }
  function describe() {
    const option = model.selectedOptions[0];
    const isManual = model.value === '__manual__';
    manualBox.hidden = !isManual;
    manual.disabled = !isManual;
    manual.required = isManual;
    const description = document.querySelector('[data-ia-model-description]');
    const title = document.querySelector('[data-ia-model-title]');
    const link = document.querySelector('[data-ia-model-link]');
    description.textContent = option?.dataset.descricao || (model.value
      ? 'O teste verifica se este modelo responde ao formato usado pelo app. Modelos de imagens, embeddings ou raciocínio longo podem não ser adequados.'
      : 'Comece pelo Nemotron 3 Super e teste com sua chave. Você também pode escolher outro modelo do catálogo.');
    title.textContent = isManual ? 'Use o mesmo modelo da sua IDE' : model.value ? option.textContent : 'Recomendação: NVIDIA Nemotron 3 Super';
    link.hidden = !option?.dataset.url;
    if (option?.dataset.url) link.href = option.dataset.url;
  }
  async function catalog() {
    if (!key.reportValidity()) return;
    const started = keyRevision;
    const data = new FormData();
    data.set('chave', key.value);
    loadModels.disabled = true;
    catalogStatus.textContent = 'Consultando o catálogo NVIDIA…';
    try {
      const response = await fetch('/api/configuracao-ia/modelos', {
        method: 'POST', body: data, headers: {'X-CSRF-Token': button.dataset.csrf, 'Accept': 'application/json'}
      });
      if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
      const answer = await response.json();
      if (keyRevision !== started) return;
      if (!response.ok || !answer.ok || !Array.isArray(answer.modelos)) {
        catalogStatus.textContent = (answer.mensagem || 'Não foi possível carregar o catálogo.') + ' Você ainda pode informar o identificador manualmente.';
        return;
      }
      // A atualização da lista nunca muda a escolha atual nem aprova o teste.
      const selected = model.value;
      const ids = new Set(answer.modelos.filter(id => typeof id === 'string' && /^[A-Za-z0-9][A-Za-z0-9._/-]{1,119}$/.test(id)));
      if (selected && selected !== '__manual__') ids.add(selected);
      const placeholder = new Option('Selecione um modelo para testar', ''); placeholder.disabled = true;
      model.replaceChildren(placeholder);
      Array.from(ids).sort((a,b) => a.localeCompare(b)).forEach(id => {
        const known = suggestions.find(item => item.id === id);
        const option = new Option(known ? known.label : id, id);
        if (known) { option.dataset.descricao = known.description; option.dataset.url = known.url; }
        model.add(option);
      });
      model.add(new Option('Informar identificador de outro modelo…', '__manual__'));
      model.value = selected;
      catalogStatus.textContent = answer.mensagem;
      if (selected && selected !== '__manual__' && !answer.modelos.includes(selected)) {
        catalogStatus.textContent += ' O modelo selecionado não consta no catálogo atual; teste ou escolha outro.';
      }
      describe();
    } catch (_) {
      if (keyRevision === started) catalogStatus.textContent = 'Não foi possível carregar o catálogo. Informe o identificador manualmente ou tente novamente.';
    } finally { loadModels.disabled = false; }
  }
  form.addEventListener('input', invalidate);
  key.addEventListener('input', () => { keyRevision++; catalogStatus.textContent = 'Chave alterada. Carregue o catálogo novamente.'; });
  model.addEventListener('change', () => { invalidate(); describe(); });
  loadModels.addEventListener('click', catalog);
  form.addEventListener('submit', event => {
    if (!receipt.value || save.disabled) { event.preventDefault(); result.textContent = 'Teste esta configuração antes de salvar.'; }
  });
  button.addEventListener('click', async () => {
    if (!form.reportValidity()) return;
    invalidate();
    const started = revision;
    const data = new FormData(form);
    button.disabled = true;
    result.textContent = 'Testando o modelo na NVIDIA… A configuração atual permanece ativa.';
    try {
      const response = await fetch('/api/configuracao-ia/testar', {
        method: 'POST', body: data, headers: {'X-CSRF-Token': button.dataset.csrf, 'Accept': 'application/json'}
      });
      if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
      const answer = await response.json();
      if (revision !== started) { result.textContent = 'Os campos mudaram durante o teste. Teste novamente a configuração atual.'; return; }
      result.textContent = answer.mensagem;
      const approved = response.ok && answer.ok === true && typeof answer.teste_token === 'string' && answer.teste_token.length > 0;
      result.dataset.ok = String(approved);
      if (approved) {
        receipt.value = answer.teste_token;
        save.disabled = false;
        expiration = setTimeout(() => { invalidate(); result.textContent = 'O teste expirou. Teste novamente para salvar.'; }, 15 * 60 * 1000);
      }
    } catch (_) {
      result.textContent = 'Não foi possível testar. Atualize a página e tente novamente.';
      result.dataset.ok = 'false';
    } finally { button.disabled = false; }
  });
  describe();
  if (form.dataset.iaConfigurada === 'true') catalog();
})();
