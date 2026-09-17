document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('[data-analise-chat]');
  if (!root) return;
  const history = root.querySelector('[data-analise-history]');
  const form = root.querySelector('[data-analise-form]');
  const input = root.querySelector('[data-analise-input]');
  const send = root.querySelector('[data-analise-send]');
  const status = root.querySelector('[data-analise-status]');
  const csrf = root.dataset.csrf;
  // O chat herda a apresentação global, sem exibir a barra de controles (040).
  const mil = root.dataset.moneyMil === 'true';
  const cut = root.dataset.moneyCentavos !== 'true';
  const conversations = [];
  let lastPlan = null;
  let activeRequest = null;

  const numberOrNull = (value) => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  const textForHistory = (value) => String(value ?? '').trim().slice(0, 1000);
  const money = (centavos) => {
    const value = numberOrNull(centavos);
    if (value === null) return '—';
    const divisor = mil ? 100000 : 100, factor = cut ? 1 : 100;
    const rounded = Math.round(Math.abs(value) * factor / divisor);
    const integer = Math.floor(rounded / factor).toLocaleString('pt-BR');
    const decimal = cut ? '' : `,${String(rounded % 100).padStart(2, '0')}`;
    return `${value < 0 && rounded ? '(' : ''}${integer}${decimal}${value < 0 && rounded ? ')' : ''}`;
  };
  const index = (value) => {
    const number = numberOrNull(value);
    return number === null ? '—' : number.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const percentual = (value) => {
    const number = numberOrNull(value);
    return number === null ? '—' : `${number.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`;
  };
  const valueText = (value, unit) => unit === 'centavos' ? money(value) : unit === 'percentual' ? percentual(value) : index(value);
  const unitTitle = (unit) => unit === 'centavos' ? (mil ? 'Valores em R$ mil' : 'Valores em R$') : unit === 'percentual' ? 'Percentual (%)' : 'Índice';
  function element(name, className, text) {
    const el = document.createElement(name);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function resize() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 156)}px`;
  }
  function remember(role, text) {
    const normalized = textForHistory(text);
    if (!normalized) return;
    conversations.push({ role, text: normalized });
    if (conversations.length > 12) conversations.splice(0, conversations.length - 12);
  }
  const historyForRequest = () => conversations.slice(-6).map(({ role, text }) => ({ role, text: textForHistory(text) }));
  function trimHistory() {
    while (history.querySelectorAll('.analise-turn').length > 10) history.querySelector('.analise-turn')?.remove();
  }
  function addMessage(question) {
    const turn = element('article', 'analise-turn');
    const questionLine = element('p', 'analise-question');
    questionLine.append(element('i', 'ph ph-user-circle'), document.createTextNode(question));
    turn.append(questionLine);
    history.append(turn);
    trimHistory();
    return turn;
  }
  function addMoney(container, value) {
    const span = element('span');
    span.dataset.reportMoney = String(value ?? '');
    span.textContent = money(value);
    container.append(span);
    return span;
  }
  function addValue(container, value, unit) {
    if (unit === 'centavos') return addMoney(container, value);
    container.textContent = valueText(value, unit);
    return container;
  }
  function memoryText(memory) {
    if (!memory) return '';
    if (typeof memory === 'string') return memory;
    if (typeof memory !== 'object') return '';
    const lines = [];
    const ac = numberOrNull(memory.ativo_circulante_centavos), pc = numberOrNull(memory.passivo_circulante_centavos);
    if (ac !== null) lines.push(`Ativo circulante: R$ ${money(ac)}`);
    if (pc !== null) lines.push(`Passivo circulante: R$ ${money(pc)}`);
    if (memory.movimentos_resultado !== undefined) lines.push(`Movimentos de resultado: ${memory.movimentos_resultado}`);
    if (Array.isArray(memory.pontos_mensais)) lines.push(`Pontos mensais considerados: ${memory.pontos_mensais.length}`);
    if (Array.isArray(memory.linhas_dre)) memory.linhas_dre.forEach((line) => {
      if (typeof line === 'string') { lines.push(line); return; }
      if (!line || typeof line !== 'object') return;
      const label = line.label || line.descricao || line.nome || 'Linha da DRE';
      const value = line.valor_centavos ?? line.valor ?? line.value;
      lines.push(numberOrNull(value) === null ? label : `${label}: R$ ${money(value)}`);
    });
    return lines.join(' · ');
  }
  function safeSourceUrl(raw) {
    if (typeof raw !== 'string' || raw.startsWith('//')) return '';
    try {
      const url = new URL(raw, window.location.origin);
      if (url.origin !== window.location.origin) return '';
      return ['/balancete', '/balanco', '/razao', '/dre', '/dre-gerencial', '/dfc', '/dfc-direto', '/dfc-indireto', '/orcamento'].includes(url.pathname) ? `${url.pathname}${url.search}${url.hash}` : '';
    } catch (_) { return ''; }
  }
  function sourceDetails(raw) {
    if (typeof raw === 'string') {
      const url = safeSourceUrl(raw);
      const names = { '/balancete': 'Balancete', '/balanco': 'Balanço patrimonial', '/razao': 'Razão', '/dre': 'DRE', '/dre-gerencial': 'DRE gerencial', '/dfc': 'DFC', '/dfc-direto': 'DFC direto', '/dfc-indireto': 'DFC indireto', '/orcamento': 'Orçamento' };
      return { label: names[url?.split(/[?#]/)[0]] || raw, url };
    }
    if (!raw || typeof raw !== 'object') return { label: '', url: '' };
    const url = safeSourceUrl(raw.url || raw.href || raw.rota || '');
    return { label: raw.titulo || raw.nome || raw.descricao || raw.label || url, url };
  }
  function appendSource(container, raw, prefix = '') {
    const source = sourceDetails(raw);
    if (!source.label) return;
    if (prefix) container.append(document.createTextNode(prefix));
    if (source.url) {
      const link = element('a', '', source.label);
      link.href = source.url;
      container.append(link);
    } else container.append(document.createTextNode(source.label));
  }
  function appendMemory(container, memory, fallbackSource) {
    if (memory && typeof memory === 'object' && !Array.isArray(memory)) {
      const components = Array.isArray(memory.componentes) ? memory.componentes : [];
      components.forEach((component) => {
        if (!component || typeof component !== 'object') return;
        const line = element('div', 'analise-memory-component');
        const title = component.titulo || component.id || 'Componente';
        line.append(element('strong', '', `${title}: `), document.createTextNode(mil ? 'R$ mil ' : 'R$ '));
        addMoney(line, component.valor_centavos);
        appendSource(line, component.origem, ' · ');
        container.append(line);
      });
      if (memory.corte_importado) container.append(element('small', 'analise-memory-note', `Corte importado: ${memory.corte_importado}`));
      if (memory.motivo) container.append(element('small', 'analise-memory-note', `Critério: ${memory.motivo}`));
    }
    const legacy = memoryText(memory);
    if (legacy) container.append(element('small', 'analise-memory-note', legacy));
    const source = safeSourceUrl(fallbackSource);
    if (source) {
      const line = element('small', 'analise-memory-note');
      const link = element('a', '', 'Abrir fonte');
      link.href = source;
      line.append(link);
      container.append(line);
    }
  }
  function makeChart(quadro) {
    const card = element('section', 'analise-chart-card');
    card.dataset.analiseChartCard = '';
    card._quadro = quadro;
    const head = element('div', 'analise-chart-head');
    head.append(element('h3', '', quadro.titulo || 'Evolução'), element('small', '', unitTitle(quadro.unidade)));
    card.append(head);
    const points = Array.isArray(quadro.pontos) ? quadro.pontos : [];
    const values = points.map((point) => numberOrNull(point?.valor)).filter((value) => value !== null);
    if (!points.length || !values.length) {
      card.append(element('p', 'muted', 'Não há pontos suficientes para desenhar este gráfico.'));
      (quadro.avisos || []).forEach((warning) => card.append(element('p', 'analise-avisos', warning)));
      if (quadro.formula) card.append(element('p', 'muted', `Fórmula: ${quadro.formula}`));
      return card;
    }
    const wrap = element('div', 'analise-chart-wrap');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'analise-chart'); svg.setAttribute('viewBox', '0 0 760 290'); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', quadro.titulo || 'Gráfico de evolução');
    const title = document.createElementNS(svg.namespaceURI, 'title');
    title.textContent = quadro.titulo || 'Gráfico de evolução'; svg.append(title);
    const left = 96, top = 20, width = 632, height = 190;
    const min = Math.min(0, ...values), max = Math.max(0, ...values), range = max - min || 1;
    for (let step = 0; step < 4; step += 1) {
      const y = top + (height / 3) * step, value = max - (range / 3) * step;
      const line = document.createElementNS(svg.namespaceURI, 'line');
      line.setAttribute('class', 'analise-chart-grid'); line.setAttribute('x1', left); line.setAttribute('x2', left + width); line.setAttribute('y1', y); line.setAttribute('y2', y);
      svg.append(line);
      const label = document.createElementNS(svg.namespaceURI, 'text');
      label.setAttribute('class', 'analise-chart-value'); label.setAttribute('x', 2); label.setAttribute('y', y + 4); label.textContent = valueText(value, quadro.unidade);
      svg.append(label);
    }
    let segment = [];
    const renderSegment = () => {
      if (segment.length < 2) { segment = []; return; }
      const path = document.createElementNS(svg.namespaceURI, 'path');
      path.setAttribute('class', 'analise-chart-line'); path.setAttribute('d', `M ${segment.map((point) => point.join(' ')).join(' L ')}`);
      svg.append(path); segment = [];
    };
    const tooltip = element('div', 'analise-chart-tooltip');
    tooltip.hidden = true;
    points.forEach((point, position) => {
      const x = left + (width / Math.max(points.length - 1, 1)) * position, numeric = numberOrNull(point.valor);
      const label = document.createElementNS(svg.namespaceURI, 'text');
      label.setAttribute('class', 'analise-chart-label'); label.setAttribute('x', x); label.setAttribute('y', 232); label.setAttribute('text-anchor', 'middle'); label.textContent = point.label || '';
      svg.append(label);
      if (numeric === null) { renderSegment(); return; }
      const y = top + height - ((numeric - min) / range) * height;
      segment.push([x, y]);
      const dot = document.createElementNS(svg.namespaceURI, 'circle');
      dot.setAttribute('class', `analise-chart-dot${point.parcial ? ' is-partial' : ''}`);
      dot.setAttribute('cx', x); dot.setAttribute('cy', y); dot.setAttribute('r', 5); dot.setAttribute('tabindex', '0'); dot.setAttribute('role', 'button');
      dot.setAttribute('aria-label', `${point.label || 'Ponto'}: ${valueText(point.valor, quadro.unidade)}${point.parcial ? ', dado parcial' : ''}`);
      const show = () => {
        const variation = numberOrNull(point.variacao_percentual);
        tooltip.textContent = `${point.label || ''}: ${valueText(point.valor, quadro.unidade)}${variation === null ? '' : ` · ${percentual(variation)}`}${point.parcial ? ' · parcial' : ''}`;
        tooltip.hidden = false;
        const scaleX = svg.clientWidth / 760, scaleY = svg.clientHeight / 290;
        tooltip.style.left = `${Math.max(4, Math.min(x * scaleX + wrap.scrollLeft - 55, wrap.clientWidth - 220))}px`;
        tooltip.style.top = `${Math.max(4, y * scaleY - 36)}px`;
      };
      dot.addEventListener('mouseenter', show); dot.addEventListener('focus', show);
      dot.addEventListener('mouseleave', () => { tooltip.hidden = true; }); dot.addEventListener('blur', () => { tooltip.hidden = true; });
      svg.append(dot);
    });
    renderSegment(); wrap.append(svg, tooltip); card.append(wrap);
    const details = element('details', 'analise-details');
    details.append(element('summary', '', `Ver memória, cortes e fontes (${points.length} pontos)`));
    const tableWrap = element('div', 'analise-table-wrap'), table = element('table', 'analise-table');
    const thead = document.createElement('thead'), headerRow = document.createElement('tr');
    ['Período', 'Valor', 'Variação', 'Memória e fonte'].forEach((label, position) => headerRow.append(element('th', position === 1 || position === 2 ? 'numeric' : '', label)));
    thead.append(headerRow);
    const tbody = document.createElement('tbody');
    points.forEach((point) => {
      const row = document.createElement('tr'), period = element('td', '', point.label || '—'), value = element('td', 'numeric'), variation = element('td', 'numeric'), memory = element('td', 'analise-memory');
      addValue(value, point.valor, quadro.unidade);
      variation.textContent = percentual(point.variacao_percentual);
      if (point.parcial) memory.append(element('small', 'analise-memory-note', 'Dado parcial.'));
      appendMemory(memory, point.memoria, point.url);
      row.append(period, value, variation, memory); tbody.append(row);
    });
    table.append(thead, tbody); tableWrap.append(table); details.append(tableWrap); card.append(details);
    if (quadro.formula) card.append(element('p', 'muted', `Fórmula: ${quadro.formula}`));
    if (Array.isArray(quadro.avisos) && quadro.avisos.length) {
      const list = element('ul', 'analise-avisos');
      quadro.avisos.forEach((warning) => list.append(element('li', '', warning)));
      card.append(list);
    }
    return card;
  }
  function responseFrames(data) {
    if (Array.isArray(data.quadros) && data.quadros.length) return data.quadros.slice(0, 6).filter((quadro) => quadro && typeof quadro === 'object');
    return data.quadro && typeof data.quadro === 'object' ? [data.quadro] : [];
  }
  function showResponse(turn, data) {
    const answer = element('div', 'analise-answer');
    const mode = element('span', `analise-mode ${data.modo === 'calculado' ? 'calculado' : ''}`);
    mode.append(element('i', data.modo === 'calculado' ? 'ph ph-calculator' : 'ph ph-sparkle'), document.createTextNode(data.modo === 'calculado' ? 'Leitura calculada' : 'Resposta com IA'));
    answer.append(mode, element('p', 'analise-answer-text', data.resposta || 'Não foi possível gerar uma leitura para esta pergunta.'));
    responseFrames(data).forEach((quadro) => answer.append(makeChart(quadro)));
    if (Array.isArray(data.avisos) && data.avisos.length) {
      const list = element('ul', 'analise-avisos');
      data.avisos.forEach((warning) => list.append(element('li', '', warning)));
      answer.append(list);
    }
    turn.append(answer);
    if (Object.prototype.hasOwnProperty.call(data, 'plano')) lastPlan = data.plano;
    remember('assistant', data.resposta || '');
  }
  async function ask(question, retryTurn) {
    if (activeRequest) return;
    status.textContent = 'Analisando os dados…'; status.classList.remove('is-error');
    const turn = retryTurn || addMessage(question);
    if (!retryTurn) { turn._historico = historyForRequest(); remember('user', question); }
    const historic = Array.isArray(turn._historico) ? turn._historico : historyForRequest();
    send.disabled = true; input.disabled = true; activeRequest = turn;
    try {
      const response = await fetch('/api/analise/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ pergunta: question, contexto: lastPlan, historico: historic })
      });
      const data = await response.json().catch(() => ({ erro: 'A resposta do servidor não pôde ser lida.' }));
      if (!response.ok || data.erro) throw new Error(data.erro || 'Não foi possível concluir a análise.');
      showResponse(turn, data); status.textContent = '';
    } catch (error) {
      status.textContent = error.message || 'Não foi possível concluir a análise.'; status.classList.add('is-error');
      const retry = element('button', 'btn btn-secondary analise-retry', 'Tentar novamente');
      retry.type = 'button';
      retry.addEventListener('click', () => { retry.remove(); ask(question, turn); });
      turn.append(retry);
    } finally {
      activeRequest = null; send.disabled = false; input.disabled = false; input.focus();
    }
  }
  const welcomeTemplate = history.querySelector('[data-analise-welcome]')?.cloneNode(true);
  function bindSuggestions(scope) {
    scope.querySelectorAll('[data-analise-suggestion]').forEach((button) => button.addEventListener('click', () => { input.value = button.textContent; resize(); input.focus(); }));
  }
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    history.querySelector('[data-analise-welcome]')?.remove();
    input.value = ''; resize(); ask(question);
  });
  input.addEventListener('input', resize);
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); } });
  bindSuggestions(root);
  document.querySelector('[data-analise-new]')?.addEventListener('click', () => {
    if (activeRequest) return;
    history.replaceChildren();
    if (welcomeTemplate) { const welcome = welcomeTemplate.cloneNode(true); history.append(welcome); bindSuggestions(welcome); }
    conversations.length = 0; lastPlan = null; status.textContent = ''; input.value = ''; resize(); input.focus();
  });
  const redrawCharts = () => setTimeout(() => document.querySelectorAll('[data-analise-chart-card]').forEach((card) => { if (card._quadro) card.replaceWith(makeChart(card._quadro)); }), 0);
  resize();
});
