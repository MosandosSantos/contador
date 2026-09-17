// Prévia do nível; o servidor recalcula a partir da estrutura ao salvar.
document.addEventListener('DOMContentLoaded', () => {
  const codigo = document.getElementById('conta_id');
  const nivel = document.getElementById('nivel-calculado');
  if (!codigo || !nivel) return;
  const atualizar = () => {
    const valor = codigo.value.trim();
    if (/^\d+(?:\.\d+)+$/.test(valor)) nivel.textContent = String(valor.split('.').length);
    else if (/^\d+$/.test(valor)) nivel.textContent = String(1 + [1, 2, 3, 5].filter(tamanho => tamanho < valor.length).length);
    else nivel.textContent = valor ? 'Calculado ao salvar' : '—';
  };
  codigo.addEventListener('input', atualizar);
  atualizar();
});
