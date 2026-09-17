/* Fonte: GENESIS 3.32.0, 01_SISTEMAS/_componentes/tabela-avancada.js.
 * Adaptação documentada em docs/COMPONENTES_V03.md: popovers no lugar dos prompts,
 * XLSX real, filtros por coluna e consulta no servidor para listas paginadas.
 */
(function (w) {
  'use strict';
  const ledgerExports=new Map();
  const make = (tag, attrs = {}) => {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([key,value]) => key === 'text' ? node.textContent = value : node.setAttribute(key,value));
    return node;
  };
  const csrf = () => document.querySelector('input[name="csrf_token"]')?.value || '';
  const norm = value => String(value ?? '').trim();
  const read = (row,c) => {const cell=row.cells[c.index];if(!cell)return '';if(cell.querySelector('[data-tree-toggle],[data-export-ignore]')){const copy=cell.cloneNode(true);copy.querySelectorAll('[data-tree-toggle],[data-export-ignore]').forEach(node=>node.remove());return norm(copy.textContent);}return norm(cell.textContent);};
  const dateStamp = () => new Date().toISOString().slice(0,10);
  function headerCells(table) {
    const leaf=table.tHead.querySelector('[data-column-headers]');
    return leaf?[...table.tHead.rows[0].cells].filter(th=>th.rowSpan>1).concat([...leaf.cells]):[...table.tHead.rows[0].cells];
  }
  function sortable(value, type) {
    if (type === 'data' && /^\d{2}\/\d{2}\/\d{4}( \d{2}:\d{2}(:\d{2})?)?$/.test(value)) return value.slice(6,10)+value.slice(3,5)+value.slice(0,2)+value.slice(10);
    if (type === 'numero') {
      const negative = /^\s*\(/.test(value) || /[−-]/.test(value);
      const number = Number(value.replace(/[^\d,.]/g,'').replace(/\./g,'').replace(',','.'));
      if (Number.isFinite(number)) return negative ? -number : number;
    }
    return value.toLocaleLowerCase('pt-BR');
  }
  function download(name, blob) {
    const url=URL.createObjectURL(blob),a=make('a',{href:url,download:name});
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function preferences(key, value) {
    const url='/api/preferencia/'+encodeURIComponent(key);
    const response=await fetch(url,value ? {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify(value),keepalive:true} : {});
    if (!response.ok) throw new Error('preferences');
    return response.json();
  }
  function init(wrap, opts={}) {
    if (!wrap || wrap.dataset.tabelaReady) return;
    const table=opts.table||wrap.querySelector('table'),body=table?.tBodies[0];
    if (!body || !table.tHead) return;
    wrap.dataset.tabelaReady='1';
    const key=opts.prefKey||wrap.dataset.prefKey,server=table.dataset.serverPageSize==='true',tree=table.dataset.tree==='true',statement=wrap.classList.contains('statement')||tree||table.dataset.lockedOrder==='true';
    const source=[...body.rows], headers=headerCells(table);
    let groupOffset=headers.filter(th=>th.rowSpan>1).length;
    const headerGroups=[...table.tHead.querySelectorAll('[data-column-group]')].map(th=>{
      const indices=Array.from({length:th.colSpan},(_,i)=>groupOffset+i);groupOffset+=th.colSpan;return {th,indices};
    });
    const nodeMap=new Map(source.map(row=>[row.dataset.nodeId,row])),collapsed=new Set();
    const treeDepth=Number(table.dataset.treeDepth||2);
    if(tree)source.forEach(row=>{if(row.querySelector('[data-tree-toggle]')&&Number(row.dataset.level)>=treeDepth-1)collapsed.add(row.dataset.nodeId);});
    const columns=headers.map((th,index)=>({th,index,key:th.dataset.colKey,label:th.dataset.exportLabel||norm(th.textContent),type:th.dataset.tipo||(th.classList.contains('numeric')?'numero':'texto')})).filter(c=>c.key);
    const params=new URL(location.href).searchParams;
    const state={ocultas:{},filtros:{},ordena:null,porPagina:Number(params.get('per_page'))||100,pagina:1};
    columns.forEach(c=>{if(params.has('cf_'+c.key))state.filtros[c.key]=params.get('cf_'+c.key);});
    if(params.has('sort'))state.ordena={col:params.get('sort'),dir:params.get('order')||'asc'};
    let ready=false, touched=false, debounce, filterRow=null;
    const header=wrap.querySelector('.section-head')||make('header',{'class':'section-head'});
    if(!header.parentElement) { header.append(make('h2',{text:opts.titulo||'Registros'}));wrap.prepend(header); }
    header.classList.add('tabela-cab');
    const actions=header.querySelector('.tabela-acoes')||make('div',{'class':'tabela-acoes'}),tools=make('div',{'class':'tab-menu-wrap'});
    const trigger=make('button',{type:'button','class':'btn-tab-menu','aria-label':'Ferramentas da tabela','aria-expanded':'false'});
    trigger.append(make('i',{'class':'ph-bold ph-list'}));
    const menu=make('div',{'class':'tab-menu',role:'menu',hidden:''});
    tools.append(trigger,menu);actions.append(tools);header.append(actions);
    const status=make('p',{'class':'tab-status',role:'status'});
    wrap.append(status);
    // Expansão é uma preferência própria; filtros/colunas não a sobrescrevem.
    // A ordem das dimensões identifica a árvore, sem incluir ano ou visão mensal.
    const persistTree=tree&&table.dataset.persistTree==='true',layout=table.dataset.treeLayout||'';
    let layoutHash=2166136261;for(const char of layout)layoutHash=Math.imul(layoutHash^char.charCodeAt(0),16777619);
    const drillKey=key+'.drill.v1.'+(layoutHash>>>0).toString(16);
    let drillState={layout,profundidade:treeDepth-1,ramos:{}},drillTouched=false,drillPending=0,drillQueue=Promise.resolve();
    function applyDrill() {
      collapsed.clear();
      source.forEach(row=>{
        if(!row.querySelector('[data-tree-toggle]'))return;
        const id=row.dataset.nodeId,expanded=drillState.ramos[id];
        if(expanded===false||(expanded!==true&&drillState.profundidade!==null&&Number(row.dataset.level)>=drillState.profundidade))collapsed.add(id);
      });
    }
    function saveDrill(level) {
      if(!persistTree)return;
      if(level!==undefined)drillState={layout,profundidade:level,ramos:{}};
      drillTouched=true;drillPending++;table.dataset.drillSaving='1';
      const payload=JSON.parse(JSON.stringify(drillState));
      drillQueue=drillQueue.then(()=>preferences(drillKey,payload)).then(()=>{
        if(status.dataset.drillError){status.textContent='';delete status.dataset.drillError;}
      }).catch(()=>{status.textContent='Não foi possível guardar o drill down. Tente expandir ou recolher novamente.';status.dataset.drillError='1';}).finally(()=>{drillPending--;table.dataset.drillSaving=drillPending?'1':'0';});
    }
    const drillLoaded=persistTree?preferences(drillKey).then(p=>{
      if(drillTouched||p.layout!==layout)return;
      if(!(p.profundidade===null||Number.isInteger(p.profundidade)&&p.profundidade>=0&&p.profundidade<=100)||!p.ramos||typeof p.ramos!=='object'||Array.isArray(p.ramos))return;
      drillState={layout,profundidade:p.profundidade,ramos:Object.fromEntries(Object.entries(p.ramos).filter(([id,value])=>id.length<=2000&&typeof value==='boolean'))};applyDrill();render();
    }).catch(()=>{status.textContent='Não foi possível recuperar o drill down salvo.';}):Promise.resolve();
    if(persistTree){
      // Termina as gravações em ordem antes de trocar rota, período ou níveis.
      document.addEventListener('click',event=>{
        const link=event.target.closest('a[href]');
        if(!drillPending||!link||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||link.target||link.hasAttribute('download'))return;
        const url=new URL(link.href,location.href);if(url.origin!==location.origin||url.hash&&url.pathname===location.pathname&&url.search===location.search)return;
        event.preventDefault();drillQueue.finally(()=>location.assign(url.href));
      },true);
      document.addEventListener('submit',event=>{
        const form=event.target;if(!drillPending||!form.matches('#dre-filtros,#dre-niveis-modal form,[data-report-choice-form],#relatorio-filtro form'))return;
        event.preventDefault();event.stopImmediatePropagation();const submitter=event.submitter;
        drillQueue.finally(()=>form.requestSubmit(submitter||undefined));
      },true);
    }
    const pager=make('div',{'class':'oc-pag',hidden:''});
    if(!server)wrap.append(pager);
    const popups=[];
    let drillTools=null, drillMenu=null, drillTrigger=null;
    function close() { menu.hidden=true;trigger.setAttribute('aria-expanded','false');popups.forEach(p=>p.hidden=true);if(drillMenu){drillMenu.hidden=true;drillTrigger.setAttribute('aria-expanded','false');} }
    function panel(title) {
      const p=make('div',{'class':'ta-popup',hidden:'','aria-label':title});
      p.append(make('strong',{'class':'ta-popup-cab',text:title}));tools.append(p);popups.push(p);return p;
    }
    function fit(p) { p.classList.remove('abre-acima');const r=p.getBoundingClientRect();if(r.bottom>innerHeight-12&&trigger.getBoundingClientRect().top>r.height+12)p.classList.add('abre-acima'); }
    function open(p) { menu.hidden=true;popups.forEach(x=>x.hidden=x!==p);p.hidden=false;fit(p); }
    function item(label, icon, fn) {
      const b=make('button',{type:'button','class':'tab-menu-item',role:'menuitem'});
      b.append(make('i',{'class':'ph '+icon}),make('span',{text:label}));b.addEventListener('click',fn);menu.append(b);return b;
    }
    function save() {
      touched=true;
      return preferences(key,{ocultas:state.ocultas,filtros:state.filtros,ordena:state.ordena,porPagina:state.porPagina}).catch(()=>{status.textContent='Não foi possível guardar as preferências.';});
    }
    function navigate(changes) {
      const url=new URL(location.href);
      Object.entries(changes).forEach(([k,v])=> v===null||v==='' ? url.searchParams.delete(k) : url.searchParams.set(k,v));
      Promise.all([save(),drillQueue]).finally(()=>location.assign(url.toString()));
    }
    function visibleRows() { return [...body.rows].filter(row=>!row.hidden); }
    function applyColumns() {
      columns.forEach(c=>{
        c.th.hidden=Boolean(state.ocultas[c.key]);
        [...source,...(table.tFoot?.rows||[])].forEach(row=>{if(row.cells[c.index])row.cells[c.index].hidden=Boolean(state.ocultas[c.key]);});
        if(filterRow?.cells[c.index])filterRow.cells[c.index].hidden=Boolean(state.ocultas[c.key]);
      });
      headerGroups.forEach(({th,indices})=>{const count=indices.filter(i=>!headers[i].hidden).length;th.hidden=count===0;th.colSpan=Math.max(1,count);});
    }
    function render() {
      applyColumns();
      if(server)return;
      let rows=source.filter(row=>columns.every(c=>!state.filtros[c.key]||read(row,c).toLocaleLowerCase('pt-BR').includes(state.filtros[c.key].toLocaleLowerCase('pt-BR'))));
      const filtering=Object.values(state.filtros).some(Boolean);
      if(tree) {
        const keep=new Set(rows.map(row=>row.dataset.nodeId));
        // Busca conserva ancestrais; filhos de um grupo correspondente acompanham o ramo.
        source.forEach(row=>{if(keep.has(row.dataset.parentId))keep.add(row.dataset.nodeId);});
        [...keep].forEach(id=>{let row=nodeMap.get(id),seen=new Set();while(row&&nodeMap.has(row.dataset.parentId)&&!seen.has(row.dataset.parentId)){seen.add(row.dataset.parentId);keep.add(row.dataset.parentId);row=nodeMap.get(row.dataset.parentId);}});
        rows=source.filter(row=>keep.has(row.dataset.nodeId));
        source.forEach(row=>{const button=row.querySelector('[data-tree-toggle]');if(button){const expanded=filtering||!collapsed.has(row.dataset.nodeId);button.setAttribute('aria-expanded',String(expanded));const label=button.getAttribute('aria-label').replace(/^(Recolher|Expandir) /,'');button.setAttribute('aria-label',(expanded?'Recolher ':'Expandir ')+label);}});
      }
      if(state.ordena&&!statement) {
        const col=columns.find(c=>c.key===state.ordena.col);
        if(col)rows.sort((a,b)=>{
          const aa=sortable(read(a,col),col.type),bb=sortable(read(b,col),col.type);
          return (typeof aa==='number'&&typeof bb==='number'?aa-bb:String(aa).localeCompare(String(bb),'pt-BR',{numeric:true}))*(state.ordena.dir==='desc'?-1:1);
        });
      }
      rows.forEach(row=>body.append(row));
      const rootOf=row=>{const seen=new Set();while(nodeMap.has(row.dataset.parentId)&&!seen.has(row.dataset.parentId)){seen.add(row.dataset.parentId);row=nodeMap.get(row.dataset.parentId);}return row.dataset.nodeId;};
      const units=tree?[...new Set(rows.map(rootOf))]:rows;
      const pages=Math.max(1,Math.ceil(units.length/state.porPagina));state.pagina=Math.min(state.pagina,pages);
      source.forEach(row=>row.hidden=true);
      const start=(state.pagina-1)*state.porPagina;
      const pageRoots=tree?new Set(units.slice(start,start+state.porPagina)):null;
      const pageRows=tree?rows.filter(row=>pageRoots.has(rootOf(row))):rows.slice(start,start+state.porPagina);
      pageRows.forEach(row=>{let parent=nodeMap.get(row.dataset.parentId),closed=false,seen=new Set();if(tree&&!filtering)while(parent&&!seen.has(parent.dataset.nodeId)){seen.add(parent.dataset.nodeId);if(collapsed.has(parent.dataset.nodeId)){closed=true;break;}parent=nodeMap.get(parent.dataset.parentId);}row.hidden=closed;});
      pager.replaceChildren();pager.hidden=false;
      pager.append(make('span',{text:rows.length ? (tree?visibleRows().length+' linhas visíveis · ':'')+(start+1)+'–'+Math.min(start+state.porPagina,units.length)+' de '+units.length+(tree?' ramos':' registros') : 'Nenhum registro para o filtro.'}));
      const nav=make('nav',{'aria-label':'Paginação da tabela','class':'oc-pag-ctrls'});
      [[1,'Primeira página','«'],[state.pagina-1,'Página anterior','‹'],[state.pagina+1,'Próxima página','›'],[pages,'Última página','»']].forEach(([page,label,text],index)=>{
        if(index===2)nav.append(make('span',{text:'Página '+state.pagina+' de '+pages}));
        const b=make('button',{type:'button','class':'btn btn-secondary','aria-label':label,text});b.disabled=page<1||page>pages||page===state.pagina;
        b.addEventListener('click',()=>{state.pagina=page;render();});nav.append(b);
      });pager.append(nav);
    }
    function sortBy(c,dir) {
      state.ordena={col:c.key,dir};state.pagina=1;
      if(server)navigate({sort:c.key,order:dir,page:1});else{render();save();}
      close();
    }
    function toggleFilters(initial=false) {
      if(filterRow&&!initial) {
        filterRow.remove();filterRow=null;state.filtros={};state.pagina=1;
        if(server){const changes={page:1};columns.forEach(c=>changes['cf_'+c.key]=null);navigate(changes);}
        else {render();save();} close();return;
      }
      if(filterRow)return;
      filterRow=make('tr',{'class':'ta-filter-row'});
      headers.forEach((th,index)=>{
        const cell=make('th'),col=columns.find(c=>c.index===index);
        if(col) {
          const input=make('input',{type:'search',placeholder:'Contém','aria-label':'Filtrar '+col.label});
          input.value=state.filtros[col.key]||'';
          input.addEventListener('input',()=>{
            state.filtros[col.key]=input.value;state.pagina=1;
            if(server) {
              clearTimeout(debounce);
              debounce=setTimeout(()=>{
                try{sessionStorage.setItem('ta-focus',key+':'+col.key);}catch(_){}
                const changes={page:1};columns.forEach(c=>changes['cf_'+c.key]=state.filtros[c.key]||null);navigate(changes);
              },650);
            } else {render();save();}
          });cell.append(input);
        }
        filterRow.append(cell);
      });
      table.tHead.append(filterRow);applyColumns();close();
    }
    const sortPanel=panel('Ordenar'),columnPanel=panel('Colunas'),sizePanel=panel('Linhas por página');
    if(statement)sortPanel.append(make('p',{'class':'tab-menu-note',text:tree?'A ordem preserva contas pai e filhas da estrutura cadastrada.':'A ordem acompanha a estrutura do demonstrativo.'}));
    else columns.forEach(c=>{
      const row=make('div',{'class':'ta-sort-row'});row.append(make('span',{text:c.label}));
      [['asc','Crescente','ph-sort-ascending'],['desc','Decrescente','ph-sort-descending']].forEach(([dir,label,icon])=>{
        const b=make('button',{type:'button','class':'btn btn-secondary','aria-label':label+' · '+c.label});b.append(make('i',{'class':'ph '+icon}));b.addEventListener('click',()=>sortBy(c,dir));row.append(b);
      });sortPanel.append(row);
      c.th.addEventListener('click',event=>{if(event.target.closest('input'))return;event.preventDefault();sortBy(c,state.ordena?.col===c.key&&state.ordena.dir==='asc'?'desc':'asc');});
    });
    const checks=new Map();
    columns.forEach(c=>{
      const row=make('div',{'class':'cmp-column-choice'}),sw=make('span',{'class':'cv-sw'});
      const input=make('input',{type:'checkbox',id:key+'-'+c.index,'aria-label':'Exibir '+c.label});input.checked=true;checks.set(c.key,input);
      const label=make('label',{for:input.id,'aria-label':'Exibir '+c.label});
      input.addEventListener('change',()=>{
        if(tree&&c.index===0&&!input.checked){input.checked=true;status.textContent='A primeira coluna identifica os ramos da árvore.';return;}
        if(!input.checked&&columns.filter(x=>!state.ocultas[x.key]).length===1){input.checked=true;status.textContent='Mantenha pelo menos uma coluna visível.';return;}
        state.ocultas[c.key]=!input.checked;applyColumns();save();
      });sw.append(input,label);row.append(make('span',{text:c.label}),sw);columnPanel.append(row);
    });
    if(tree)sizePanel.append(make('p',{'class':'tab-menu-note',text:'A quantidade é de ramos completos; contas filhas acompanham o pai.'}));
    [10,50,100,500].forEach(size=>{
      const b=make('button',{type:'button','class':'ta-option',text:String(size)});
      b.addEventListener('click',()=>{state.porPagina=size;state.pagina=1;if(server)navigate({per_page:size,page:1});else{render();save();close();}});sizePanel.append(b);
    });
    function exportPayload(allColumns=false) {
      const shown=columns.filter(c=>allColumns||!state.ocultas[c.key]);
      const label=c=>{
        const title=c.th.dataset.exportLabel||norm(c.th.textContent),unit=document.querySelector('[data-report-unit]')?.textContent;
        const monetary=source.some(row=>row.cells[c.index]?.querySelector('[data-report-money]'));
        return monetary&&unit&&!title.includes('R$')?title+' ('+unit+')':title;
      };
      const account=table.dataset.exportAccount;
      // O Razão exporta o período completo, incluindo abertura e fechamento,
      // independentemente da página ou da busca visual na tabela.
      const exportRows=account!==undefined?source:[...visibleRows(),...(table.tFoot?.rows||[])];
      if(table.dataset.comparisonTable==='true') {
        const fields=['Orçado','Realizado','Variação','Variação %'];
        const unit=document.querySelector('[data-report-unit]')?.textContent||'R$';
        const targets=shown.flatMap(c=>c.th.hasAttribute('data-comparison-column')?fields.map(field=>({c,field})):[{c,field:null}]);
        const colunas=targets.map(({c,field})=>field?(c.th.dataset.exportLabel||c.label)+' · '+field+(field.endsWith('%')?'':' ('+unit+')'):label(c));
        const linhas=exportRows.filter(row=>row.dataset.exportSkip!=='true').map(row=>targets.map(({c,field})=>field?norm(row.cells[c.index]?.querySelector('[data-export-field="'+field+'"]')?.innerText):read(row,c)));
        return {colunas,linhas,nome:key+'_'+dateStamp()};
      }
      const colunas=shown.map(label),linhas=exportRows.filter(row=>row.dataset.exportSkip!=='true').map(row=>shown.map(c=>read(row,c)));
      if(account!==undefined){colunas.unshift('Código da conta');linhas.forEach(row=>row.unshift(account));}
      return {colunas,linhas,nome:key+'_'+dateStamp()};
    }
    if(table.dataset.exportAccount!==undefined)ledgerExports.set(table,()=>exportPayload(true));
    function allLedgerPayload() {
      const parts=[...ledgerExports].filter(([t])=>t.isConnected).map(([,build])=>build());
      return {colunas:parts[0].colunas,linhas:parts.flatMap(p=>p.linhas),nome:'razao_todas_contas_'+dateStamp()};
    }
    function csvCell(value) {
      let text=norm(value);if(/^[=+\-@]/.test(text))text="'"+text;
      return /[;",\r\n]/.test(text)?'"'+text.replace(/"/g,'""')+'"':text;
    }
    function exportCsv(allAccounts=false) {
      const data=allAccounts?allLedgerPayload():exportPayload(),rows=[data.colunas,...data.linhas].map(row=>row.map(csvCell).join(';')).join('\r\n');
      download(data.nome+'.csv',new Blob(['\ufeff'+rows],{type:'text/csv;charset=utf-8'}));close();
    }
    async function exportExcel(allAccounts=false) {
      const data=allAccounts?allLedgerPayload():exportPayload();status.textContent='Gerando arquivo…';close();
      try {
        const response=await fetch('/exportar/tabela.xlsx',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf()},body:JSON.stringify(data)});
        if(!response.ok)throw new Error('export');
        download(data.nome+'.xlsx',await response.blob());status.textContent='Arquivo Excel baixado.';
      } catch(_) {status.textContent='Não foi possível gerar o Excel. Atualize a página e tente novamente.';}
    }
    item('Filtro por coluna','ph-funnel',()=>toggleFilters());
    if(tree) {
      const changeAll=expand=>{collapsed.clear();if(!expand)source.forEach(row=>{if(row.querySelector('[data-tree-toggle]'))collapsed.add(row.dataset.nodeId);});render();saveDrill(expand?null:0);close();};
      if(table.dataset.dreHierarchy==='true'||table.dataset.reportHierarchy==='true') {
        const avTemplate=wrap.querySelector('template[data-dre-av-options]');
        if(avTemplate) {
          const avPanel=panel('Base AV');avPanel.setAttribute('role','menu');
          avPanel.append(avTemplate.content.cloneNode(true));
          avPanel.addEventListener('click',event=>{const option=event.target.closest('[data-av-base]');if(option)navigate({base_av:option.dataset.avBase});});
          item('Base AV','ph-percent',()=>open(avPanel)).setAttribute('aria-label','Base AV');
        }
        [['Selecionar Níveis','ph-tree-structure','contas'],['Centro de custo no drill down','ph-buildings','centro']].forEach(([label,icon,modo])=>{
          const b=item(label,icon,()=>{close();document.dispatchEvent(new CustomEvent('dre-niveis:abrir',{detail:{modo}}));});
          b.dataset.editModal='dre-niveis-modal';
        });
        drillTools=make('div',{'class':'tab-menu-wrap'});
        drillTrigger=make('button',{type:'button','class':'btn-tab-menu dre-drill-trigger','aria-label':'Opções de drill down',title:'Opções de drill down','aria-expanded':'false'});
        drillTrigger.append(make('i',{'class':'ph ph-tree-structure','aria-hidden':'true'}));
        drillMenu=make('div',{'class':'tab-menu dre-drill-menu',role:'menu',hidden:''});
        drillTools.append(drillTrigger,drillMenu);actions.insertBefore(drillTools,tools);
        const maxLevel=Math.max(0,...source.map(row=>Number(row.dataset.level)));
        function depth(mode) {
          close();
          if(Object.values(state.filtros).some(Boolean)){status.textContent='Limpe os filtros por coluna para usar os comandos de drill down.';return;}
          const visibleLevel=Math.max(0,...visibleRows().map(row=>Number(row.dataset.level)));
          const level=mode==='all'?maxLevel:mode==='first'?0:Math.max(0,Math.min(maxLevel,visibleLevel+(mode==='next'?1:-1)));
          collapsed.clear();
          source.forEach(row=>{if(row.querySelector('[data-tree-toggle]')&&Number(row.dataset.level)>=level)collapsed.add(row.dataset.nodeId);});
          render(); status.textContent='Detalhamento até o nível '+(level+1)+' de '+(maxLevel+1)+'.';
          saveDrill(mode==='all'?null:level);
          drillTrigger.focus();
        }
        [['Expandir todos até o último nível','all','ph-arrows-out-simple'],['Expandir até o próximo nível','next','ph-arrow-down'],['Recolher até o primeiro nível','first','ph-arrows-in-simple'],['Recolher até o penúltimo nível','previous','ph-arrow-up']].forEach(([label,mode,icon])=>{
          const b=make('button',{type:'button','class':'tab-menu-item',role:'menuitem'});
          if(mode==='previous')b.title='Voltar um nível em relação ao detalhamento visível';
          b.append(make('i',{'class':'ph '+icon}),make('span',{text:label}));b.addEventListener('click',()=>depth(mode));drillMenu.append(b);
        });
        drillTrigger.addEventListener('click',event=>{event.stopPropagation();const expanded=drillMenu.hidden;close();drillMenu.hidden=!expanded;drillTrigger.setAttribute('aria-expanded',String(expanded));if(expanded)fit(drillMenu);});
        drillTools.addEventListener('keydown',event=>{if(event.key==='Escape'){close();drillTrigger.focus();}});
      } else {
        item('Expandir tudo','ph-arrows-out-simple',()=>changeAll(true));
        item('Recolher tudo','ph-arrows-in-simple',()=>changeAll(false));
      }
      body.addEventListener('click',event=>{const button=event.target.closest('[data-tree-toggle]');if(!button)return;const id=button.closest('tr').dataset.nodeId;if(Object.values(state.filtros).some(Boolean)){status.textContent='Limpe os filtros para recolher os ramos; a busca mantém o caminho visível.';return;}collapsed.has(id)?collapsed.delete(id):collapsed.add(id);if(persistTree){drillState.ramos[id]=!collapsed.has(id);saveDrill();}render();});
    }
    item('Ordenar','ph-arrows-down-up',()=>open(sortPanel));
    item('Colunas','ph-columns',()=>open(columnPanel));
    menu.append(make('div',{'class':'tab-menu-sep'}));
    item('Exportar CSV','ph-file-csv',()=>exportCsv());item('Exportar Excel','ph-file-xls',()=>exportExcel());
    if(table.dataset.exportAccount!==undefined&&document.querySelectorAll('table[data-export-account]').length>1){
      item('Exportar todas as contas (CSV)','ph-file-csv',()=>exportCsv(true));
      item('Exportar todas as contas (Excel)','ph-file-xls',()=>exportExcel(true));
    }
    menu.append(make('div',{'class':'tab-menu-sep'}));item('Linhas por página','ph-list-numbers',()=>open(sizePanel));
    trigger.addEventListener('click',event=>{event.stopPropagation();const expanded=menu.hidden;close();menu.hidden=!expanded;trigger.setAttribute('aria-expanded',String(expanded));if(expanded)fit(menu);});
    document.addEventListener('click',event=>{if(!tools.contains(event.target)&&!drillTools?.contains(event.target))close();});
    tools.addEventListener('keydown',event=>{if(event.key==='Escape'){close();trigger.focus();}});
    render();
    Promise.all([preferences(key),drillLoaded]).then(([p])=>{
      if(touched){ready=true;table.dataset.prefReady='1';return;}
      state.ocultas=p.ocultas||{};
      if(tree&&columns.length)delete state.ocultas[columns[0].key];
      if(!server){state.filtros=p.filtros||{};if(!statement)state.ordena=p.ordena||null;if([10,50,100,500].includes(p.porPagina))state.porPagina=p.porPagina;}
      if(columns.every(c=>state.ocultas[c.key])&&columns.length)delete state.ocultas[columns[0].key];
      checks.forEach((check,k)=>check.checked=!state.ocultas[k]);ready=true;render();table.dataset.prefReady='1';
      if(Object.values(state.filtros).some(Boolean))toggleFilters(true);
      try {
        const focus=sessionStorage.getItem('ta-focus');
        const col=columns.find(c=>focus===key+':'+c.key);
        if(col&&filterRow){const input=filterRow.cells[col.index].querySelector('input');input.focus();input.setSelectionRange(input.value.length,input.value.length);sessionStorage.removeItem('ta-focus');}
      } catch(_){}
    }).catch(()=>{ready=true;table.dataset.prefReady='1';});
  }
  w.TabelaAvancada={init,headerCells};
})(window);
