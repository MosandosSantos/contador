document.addEventListener('DOMContentLoaded',()=>{
  const tipo=document.getElementById('balancete-tipo');
  const initial=tipo.elements.tipo.value;
  tipo.addEventListener('component:choice',event=>{if(event.detail.value!==initial)tipo.requestSubmit();});
  const form=document.querySelector('#balancete-filtro form');
  function validate(){
    const de=form.elements.data_de,ate=form.elements.data_ate;
    ate.setCustomValidity(de.value&&ate.value&&de.value>ate.value?'Data Até deve ser igual ou posterior à Data De.':'');
  }
  form.addEventListener('input',validate);form.addEventListener('change',validate);
});
