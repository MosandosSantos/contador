// Componente único de edição: dados do registro, validação e retorno ao contexto.
(() => {
  'use strict';
  const owners = new WeakMap();
  function clear(dialog) {
    const alert = dialog.querySelector('.modal-aviso'); alert.hidden = true; alert.replaceChildren();
    dialog.querySelectorAll('[aria-invalid]').forEach(el => el.removeAttribute('aria-invalid'));
    dialog.querySelectorAll('.campo-invalido').forEach(el => el.classList.remove('campo-invalido'));
  }
  function showErrors(dialog, problems) {
    const alert = dialog.querySelector('.modal-aviso'), list = document.createElement('ul');
    problems.forEach(({message, field}) => {
      const item = document.createElement('li'); item.textContent = message; list.append(item);
      if (field) { field.setAttribute('aria-invalid', 'true'); field.classList.add('campo-invalido'); }
    });
    const help = document.createElement('p'); help.textContent = 'Corrija os campos ou feche em Cancelar para descartar.';
    alert.replaceChildren(list, help); alert.hidden = false;
    const field = problems.find(p => p.field)?.field;
    if (field) (field.closest('.cmp-selectbusca')?.querySelector('.cmp-select-display') || field).focus();
    dialog.querySelector('.modal-corpo').scrollTop = 0;
  }
  function open(dialog, trigger) {
    clear(dialog); owners.set(dialog, trigger || document.activeElement);
    const form = dialog.querySelector('form');
    if (trigger?.dataset.createModal) {
      form.reset();
      [...form.elements].forEach(field => {
        field.dispatchEvent(new Event('change', {bubbles:true}));
        field.dispatchEvent(new Event('input', {bubbles:true}));
      });
    }
    if (trigger?.dataset.record) {
      form.reset();
      const record = JSON.parse(trigger.dataset.record);
      Object.entries(record).forEach(([name, value]) => {
        const field = form.elements.namedItem(name);
        if (field && name !== 'csrf_token') { field.value = value ?? ''; field.dispatchEvent(new Event('change', {bubbles:true})); }
      });
    }
    if (trigger?.dataset.editAction) form.action = trigger.dataset.editAction;
    dialog.querySelectorAll('select').forEach(el => window.Componentes?.initSelect(el));
    dialog.showModal();
    const first = dialog.querySelector('input:not([type="hidden"]):not([readonly]), .cmp-select-display');
    if (first) first.focus();
  }
  function close(dialog) {
    if (dialog.dataset.saving) return;
    dialog.close();
    dialog.querySelectorAll('.cmp-select-panel').forEach(panel => panel.hidden = true);
    dialog.querySelectorAll('[aria-expanded]').forEach(el => el.setAttribute('aria-expanded', 'false'));
    owners.get(dialog)?.focus();
    if (dialog.dataset.returnUrl && !dialog.dataset.loaded) location.assign(dialog.dataset.returnUrl);
    if (dialog.dataset.loaded) dialog.remove();
  }
  document.addEventListener('cancel', event => {
    if (event.target.matches('dialog[data-record-modal]')) event.preventDefault();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && event.target.closest('dialog[data-record-modal]')) event.preventDefault();
  });
  document.addEventListener('click', async event => {
    const closeButton = event.target.closest('[data-modal-close]');
    if (closeButton) { close(closeButton.closest('dialog')); return; }
    const trigger = event.target.closest('[data-create-modal],[data-edit-modal],[data-edit-url]');
    if (!trigger) return;
    event.preventDefault();
    if (trigger.dataset.loading) return;
    if (trigger.dataset.createModal) { open(document.getElementById(trigger.dataset.createModal), trigger); return; }
    if (trigger.dataset.editModal) { open(document.getElementById(trigger.dataset.editModal), trigger); return; }
    trigger.dataset.loading = '1'; trigger.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(trigger.href, {headers:{Accept:'text/html'}});
      if (!response.ok) throw new Error();
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const dialog = doc.querySelector('dialog[data-record-modal]');
      if (!dialog) throw new Error();
      // O cadastro continua na página; os IDs do formulário de edição são únicos.
      dialog.querySelectorAll('[id]').forEach(el => el.id = 'edit-' + el.id);
      dialog.setAttribute('aria-labelledby', 'edit-' + dialog.getAttribute('aria-labelledby'));
      dialog.querySelectorAll('[for]').forEach(el => el.setAttribute('for', el.getAttribute('for').split(' ').map(id => 'edit-' + id).join(' ')));
      dialog.dataset.loaded = '1'; document.body.append(dialog); open(dialog, trigger);
    } catch (_) {
      let notice = document.getElementById('modal-load-error');
      if (!notice) { notice = document.createElement('div'); notice.id = 'modal-load-error'; notice.className = 'notice notice-error'; notice.setAttribute('role','alert'); document.querySelector('.content').prepend(notice); }
      notice.textContent = 'Não foi possível abrir a edição. Atualize a página e tente novamente.'; notice.scrollIntoView({block:'center'});
    } finally { delete trigger.dataset.loading; trigger.removeAttribute('aria-busy'); }
  });
  ['input','change'].forEach(name => document.addEventListener(name, event => {
    if (!event.target.closest('dialog[data-record-modal]')) return;
    event.target.removeAttribute('aria-invalid'); event.target.classList.remove('campo-invalido');
  }));
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!form.matches('[data-modal-form]')) return;
    event.preventDefault(); const dialog = form.closest('dialog');
    if (dialog.dataset.saving) return;
    clear(dialog);
    const problems = [...form.elements].filter(el => el.willValidate && !el.validity.valid).map(field => ({field, message: (field.labels?.[0]?.textContent.trim() || field.name) + ': ' + (field.validity.valueMissing ? 'preencha este campo.' : 'confira o valor informado.')}));
    if (problems.length) { showErrors(dialog, problems); return; }
    const buttons = [...dialog.querySelectorAll('button[type="submit"], [data-modal-close]')];
    dialog.dataset.saving = '1'; form.setAttribute('aria-busy','true'); buttons.forEach(b => b.disabled = true);
    try {
      const response = await fetch(form.action, {method:'POST',body:new FormData(form),headers:{Accept:'application/json','X-Record-Modal':'1'}});
      const data = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
      if (!response.ok || !data?.ok) {
        showErrors(dialog, [{message:data?.message || (response.status === 400 ? 'A sessão expirou ou o envio é inválido. Atualize a página antes de tentar novamente.' : 'Não foi possível salvar. Confira a conexão e tente novamente.')}]); return;
      }
      dialog.close();
      location.assign(dialog.dataset.loaded ? location.href : (dialog.dataset.returnUrl || location.href));
    } catch (_) { showErrors(dialog, [{message:'Não foi possível confirmar o salvamento. Confira a conexão e tente novamente.'}]); }
    finally { delete dialog.dataset.saving; form.removeAttribute('aria-busy'); buttons.forEach(b => b.disabled = false); }
  });
  document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('[data-modal-auto]').forEach(dialog => open(dialog)));
})();
