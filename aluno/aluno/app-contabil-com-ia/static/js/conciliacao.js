(function () {
  'use strict';
  function initUpload(form) {
    if (!form || form.dataset.concReady) return;
    form.dataset.concReady = '1';
    const state = {}, max = 12 * 1024 * 1024;
    const submit = form.querySelector('[data-conc-submit]');
    const feedback = form.querySelector('[data-conc-feedback]');
    const inputs = [...form.querySelectorAll('[data-conc-input]')];
    const validFile = file => file && /\.(csv|xlsx)$/i.test(file.name);
    function render(message, error) {
      const both = inputs.every(input => state[input.dataset.concInput]);
      submit.disabled = !both;
      feedback.textContent = message || (both ? 'Os dois arquivos estão prontos para conciliar.' : 'Selecione os dois arquivos para continuar.');
      feedback.classList.toggle('is-error', Boolean(error));
    }
    function load(input, file) {
      const key = input.dataset.concInput, drop = form.querySelector('[data-conc-drop="'+key+'"]');
      if (!validFile(file)) { state[key] = false; drop.classList.remove('is-loaded'); drop.querySelector('[data-conc-icon]').className = 'ph ph-file-arrow-up'; drop.querySelector('[data-conc-title]').textContent = 'Selecione o arquivo ' + (key === 'contabil' ? 'contábil' : 'financeiro'); drop.querySelector('[data-conc-name]').textContent = 'Nenhum arquivo selecionado'; render('Use um arquivo CSV ou XLSX.', true); input.value = ''; return; }
      const total = inputs.reduce((sum, field) => sum + (field === input ? file.size : (field.files[0]?.size || 0)), 0);
      if (total > max) { state[key] = false; drop.classList.remove('is-loaded'); drop.querySelector('[data-conc-icon]').className = 'ph ph-file-arrow-up'; drop.querySelector('[data-conc-title]').textContent = 'Selecione o arquivo ' + (key === 'contabil' ? 'contábil' : 'financeiro'); drop.querySelector('[data-conc-name]').textContent = 'Nenhum arquivo selecionado'; render('Os dois arquivos juntos devem ter no máximo 12 MB.', true); input.value = ''; return; }
      state[key] = true; drop.classList.add('is-loaded');
      drop.querySelector('[data-conc-icon]').className = 'ph ph-check-circle';
      drop.querySelector('[data-conc-title]').textContent = 'Arquivo selecionado';
      drop.querySelector('[data-conc-name]').textContent = file.name;
      render();
    }
    form.addEventListener('submit', () => { if (!form.checkValidity()) return; submit.disabled = true; submit.setAttribute('aria-busy', 'true'); feedback.textContent = 'Conferindo os dois relatórios…'; });
    window.addEventListener('pageshow', () => inputs.forEach(input => { if (input.files[0]) load(input, input.files[0]); }));
    inputs.forEach(input => {
      const drop = form.querySelector('[data-conc-drop="'+input.dataset.concInput+'"]');
      input.addEventListener('change', () => load(input, input.files[0]));
      drop.tabIndex = 0;
      drop.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
      ['dragenter','dragover'].forEach(type => drop.addEventListener(type, event => { event.preventDefault(); drop.classList.add('is-over'); }));
      ['dragleave','drop'].forEach(type => drop.addEventListener(type, event => { event.preventDefault(); drop.classList.remove('is-over'); }));
      drop.addEventListener('drop', event => { const file = event.dataTransfer?.files[0]; if (!file) return; const transfer = new DataTransfer(); transfer.items.add(file); input.files = transfer.files; load(input, file); });
    });
  }
  document.addEventListener('DOMContentLoaded', () => initUpload(document.querySelector('[data-conc-upload]')));
}());
