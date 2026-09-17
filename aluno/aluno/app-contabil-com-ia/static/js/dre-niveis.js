(() => {
  'use strict';
  const dialog = document.getElementById('dre-niveis-modal');
  if (!dialog) return;
  const list = dialog.querySelector('#dre-niveis-lista'), initial = [...list.children];
  let dragging = null;
  function sync() {
    const rows = [...list.children], selected = rows.filter(row => row.querySelector('input').checked);
    dialog.querySelector('[name="niveis"]').value = JSON.stringify(selected.map(row => row.dataset.nivel));
    rows.forEach((row, index) => {
      row.classList.toggle('is-off', !row.querySelector('input').checked);
      row.querySelector('[data-mover="-1"]').disabled = index === 0;
      row.querySelector('[data-mover="1"]').disabled = index === rows.length - 1;
    });
    dialog.querySelector('#dre-niveis-resumo').textContent = 'Ordem: ' + (dialog.querySelector('[data-root-label]')?.dataset.rootLabel || 'Grupo DRE') + selected.map(row => ' → ' + row.querySelector('.dre-nivel-nome').textContent).join('');
  }
  // O evento prepara o formulário; a abertura usa o mesmo componente dos cadastros.
  document.addEventListener('dre-niveis:abrir', event => {
    initial.forEach(row => { row.querySelector('input').checked = row.dataset.inicial === 'true'; list.append(row); });
    dialog.querySelector('h2').textContent = event.detail.modo === 'centro' ? 'Centro de custo no drill down' : 'Selecionar níveis';
    sync();
  });
  list.addEventListener('change', sync);
  list.addEventListener('click', event => {
    const button = event.target.closest('[data-mover]');
    if (!button) return;
    const row = button.closest('li');
    if (button.dataset.mover === '-1' && row.previousElementSibling) list.insertBefore(row, row.previousElementSibling);
    if (button.dataset.mover === '1' && row.nextElementSibling) list.insertBefore(row.nextElementSibling, row);
    sync(); button.focus();
  });
  list.addEventListener('dragstart', event => {
    if (!event.target.closest('.dre-drag')) { event.preventDefault(); return; }
    dragging = event.target.closest('li'); dragging.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', dragging.dataset.nivel);
  });
  list.addEventListener('dragover', event => {
    if (!dragging) return;
    event.preventDefault(); event.dataTransfer.dropEffect = 'move';
    const target = event.target.closest('li');
    if (!target || target === dragging) return;
    const rect = target.getBoundingClientRect();
    list.insertBefore(dragging, event.clientY < rect.top + rect.height / 2 ? target : target.nextSibling);
  });
  list.addEventListener('drop', event => { if (dragging) { event.preventDefault(); sync(); } });
  list.addEventListener('dragend', () => { dragging?.classList.remove('is-dragging'); dragging = null; sync(); });
  sync();
})();
