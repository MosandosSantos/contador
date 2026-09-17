document.addEventListener('DOMContentLoaded',()=>{
  const dialog=document.getElementById('relatorio-filtro'),form=dialog?.querySelector('form');
  if(!form)return;
  const validate=()=>form.elements.data_ate.setCustomValidity(form.elements.data_de.value>form.elements.data_ate.value?'Data Até deve ser igual ou posterior à Data De.':'');
  form.addEventListener('input',validate);form.addEventListener('change',validate);
  const search=form.querySelector('[data-account-search]');
  const filter=()=>form.querySelectorAll('[data-account-option]').forEach(row=>row.hidden=!row.textContent.toLocaleLowerCase('pt-BR').includes(search.value.trim().toLocaleLowerCase('pt-BR')));
  search?.addEventListener('input',filter);
  document.addEventListener('click',event=>{
    if(!event.target.closest('[data-edit-modal="relatorio-filtro"]'))return;
    form.reset();form.querySelectorAll('select').forEach(s=>s.dispatchEvent(new Event('change',{bubbles:true})));validate();if(search)filter();
  },true);
  document.querySelectorAll('[data-report-choice-form]').forEach(f=>{
    const field=f.querySelector('input[data-choice-value]')||f.querySelector('[data-choice-group] input[type=hidden]');
    const initial=field?.value;
    f.addEventListener('component:choice',event=>{if(event.detail.value!==initial)f.requestSubmit();});
  });
});