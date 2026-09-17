// Controles do período na faixa fixa; a consulta mantém a base de AV selecionada.
document.addEventListener('DOMContentLoaded', () => {
  const form=document.getElementById('dre-filtros');
  if(!form)return;
  const initial=form.elements.visao.value;
  form.querySelector('[name="ano"]').addEventListener('change',()=>form.requestSubmit());
  form.addEventListener('component:choice',event=>{
    if(event.detail.value!==initial)form.requestSubmit();
  });
});
