document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.querySelector('[data-sidebar-toggle]');
  toggle?.addEventListener('click', () => { const open = sidebar.classList.toggle('is-open'); toggle.setAttribute('aria-expanded', String(open)); });
  const navGroups = sidebar?.querySelectorAll('[data-nav-group]') || [];
  navGroups.forEach(group => {
    const button = group.querySelector('.grupo-cab');
    button.addEventListener('click', () => {
      const open = !group.classList.contains('aberto');
      navGroups.forEach(item => {
        const expanded = item === group && open;
        item.classList.toggle('aberto', expanded);
        item.querySelector('.grupo-cab').setAttribute('aria-expanded', String(expanded));
        item.querySelector('.grupo-corpo').hidden = !expanded;
      });
    });
  });
  document.addEventListener('keydown', e => { if(e.key === 'Escape') { sidebar?.classList.remove('is-open'); toggle?.setAttribute('aria-expanded','false'); } });
  const bars = [...document.querySelectorAll('[data-chart-value]')];
  const max = Math.max(1, ...bars.map(b => Math.abs(Number(b.dataset.chartValue) || 0)));
  bars.forEach(b => b.style.width = Math.max(2, Math.abs(Number(b.dataset.chartValue) || 0) / max * 100) + '%');
  document.querySelectorAll('[data-file-name]').forEach(input => {
    const form = input.closest('form'), zone = form.querySelector('[data-dropzone]');
    const name = form.querySelector(input.dataset.fileName), submit = form.querySelector('[data-upload-submit]'), feedback = form.querySelector('[data-upload-feedback]');
    const extensions = input.accept.split(',').filter(x => x.startsWith('.'));
    const setFile = () => {
      const file = input.files[0];
      const valid = Boolean(file && extensions.some(ext => file.name.toLowerCase().endsWith(ext)) && file.size <= 12 * 1024 * 1024);
      if(name) name.textContent = file ? file.name + ' (' + (file.size / 1024).toLocaleString('pt-BR', {maximumFractionDigits:1}) + ' KB)' : 'Nenhum arquivo selecionado';
      if(feedback) { feedback.textContent = !file ? '' : valid ? 'Arquivo pronto para conferência.' : file.size > 12 * 1024 * 1024 ? 'O arquivo excede 12 MB.' : 'Use um arquivo ' + extensions.join(' ou ') + '.'; feedback.classList.toggle('erro', Boolean(file && !valid)); feedback.classList.toggle('ok', valid); }
      zone?.classList.toggle('loaded', valid); zone?.classList.toggle('is-loaded', valid); zone?.classList.remove('over','is-over');
      const icon = zone?.querySelector('i'); if(icon) icon.className = 'ph ' + (valid ? 'ph-check-circle' : 'ph-file-arrow-up');
      if(submit) submit.disabled = !valid;
      input.setCustomValidity(file && !valid ? 'Escolha um arquivo no formato aceito, com até 12 MB.' : '');
    };
    input.addEventListener('change',setFile);
    zone?.addEventListener('keydown',e=> { if(e.key==='Enter' || e.key===' ') { e.preventDefault(); input.click(); } });
    zone?.addEventListener('dragover', e=> { e.preventDefault(); zone.classList.add('over','is-over'); });
    zone?.addEventListener('dragleave',()=>zone.classList.remove('over','is-over'));
    zone?.addEventListener('drop', e=> { e.preventDefault(); zone.classList.remove('over','is-over'); if(e.dataTransfer.files.length) { const transfer = new DataTransfer(); transfer.items.add(e.dataTransfer.files[0]); input.files=transfer.files; setFile(); } });
    form.addEventListener('submit',()=> { if(!form.checkValidity()) return; if(submit) { submit.disabled=true; submit.setAttribute('aria-busy','true'); submit.textContent='Conferindo arquivo…'; } if(feedback) feedback.textContent='Aguarde a conferência dos dados.'; });
    window.addEventListener('pageshow', setFile);
    setFile();
  });
});
