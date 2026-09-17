// Somente apresentação. Os atributos conservam os valores originais em centavos.
document.addEventListener('DOMContentLoaded', () => {
  const toolbar=document.querySelector('[data-report-presentation]');
  if(!toolbar)return;
  const mil=document.getElementById('report-mil'),centavos=document.getElementById('report-centavos'),aviso=toolbar.querySelector('[data-report-format-error]');
  // O símbolo riscado significa ocultar: a API conserva centavos=mostrar.
  const state=()=>({mil:mil.checked,centavos:!centavos.checked});
  function render(){
    const divisor=mil.checked?100000n:100n,fator=centavos.checked?1n:100n;
    document.querySelectorAll('[data-report-money]').forEach(el=>{
      const raw=el.dataset.reportMoney;
      if(raw===''){el.textContent='—';return;}
      const valor=BigInt(raw),abs=valor<0n?-valor:valor,arredondado=(abs*fator+divisor/2n)/divisor;
      const inteiro=(arredondado/fator).toLocaleString('pt-BR'),fracao=centavos.checked?'':','+(arredondado%100n).toString().padStart(2,'0');
      const texto=inteiro+fracao;el.textContent=valor<0n&&arredondado!==0n?'('+texto+')':texto;
      const sign=el.parentElement.querySelector(':scope > [data-report-minus]');if(sign)sign.hidden=arredondado===0n;
    });
    document.querySelectorAll('[data-report-unit]').forEach(el=>el.textContent=mil.checked?'R$ mil':'R$');
  }
  let saved=state();
  async function change(){
    render();aviso.hidden=true;mil.disabled=true;centavos.disabled=true;
    try{
      const response=await fetch('/api/preferencia/relatorios_apresentacao',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':toolbar.dataset.csrf},body:JSON.stringify(state())});
      if(!response.ok)throw new Error();
      saved=state();
      const url=new URL(window.location.href);
      url.searchParams.delete('mil');url.searchParams.delete('centavos');
      window.history.replaceState(window.history.state,'',url);
    }catch(_){mil.checked=saved.mil;centavos.checked=!saved.centavos;render();aviso.textContent='Não foi possível guardar a apresentação. Tente novamente.';aviso.hidden=false;}
    finally{mil.disabled=false;centavos.disabled=false;}
  }
  mil.addEventListener('change',change);centavos.addEventListener('change',change);
});
