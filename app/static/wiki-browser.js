/* Encyclopedia browser experience — loaded after app.js to replace legacy wiki layout. */
var WIKI_FEATURE_SEED = 0;
var WIKI_ORDER = ['人物','蛊虫','势力','仙蛊屋','灾劫','杀招','境界流派'];
var WIKI_LABELS = { '人物':'人物', '蛊虫':'蛊虫', '势力':'势力', '仙蛊屋':'仙蛊屋', '灾劫':'灾劫', '杀招':'杀招', '境界流派':'境界与流派' };
function wikiItems(cat){ return (WIKI && WIKI.categories && WIKI.categories[cat]) || []; }
function wikiCard(entry, cat, compact){
  var card = document.createElement('button'); card.type = 'button'; card.className = compact ? 'wiki-feature-card' : 'wiki-entry-card';
  card.innerHTML = '<span class="wiki-card-meta">'+esc(WIKI_LABELS[cat] || cat)+(entry.sub && entry.sub !== '其他' ? ' · '+esc(entry.sub) : '')+'</span><strong>'+esc(entry.name)+'</strong><span class="wiki-card-copy">'+esc(wikiExcerpt(entry.desc, compact ? 72 : 110))+'</span><span class="wiki-card-link">查看条目</span>';
  card.onclick = function(){ openWikiEntry(entry, cat); }; return card;
}
function wikiShow(view){
  $('wiki-home').hidden = view !== 'home'; $('wiki-results').hidden = view !== 'results'; $('wiki-detail').hidden = view !== 'detail';
  $('wiki-browser').dataset.view = view;
}
async function loadWiki(){
  if (WIKI) { renderWikiHome(); return; }
  try {
    var response = await fetch('/api/wiki'); if (!response.ok) throw new Error('百科数据加载失败'); WIKI = await response.json();
    WIKI_SUBS = {}; wikiItems('蛊虫').forEach(function(e){ var k=e.sub||'其他'; WIKI_SUBS[k]=(WIKI_SUBS[k]||0)+1; }); renderWikiHome();
  } catch(e) { $('wiki-home-body').innerHTML = '<div class="empty">百科数据暂时无法加载</div>'; }
}
function renderWikiHome(){
  if (!WIKI) return; wikiShow('home');
  var total = 0, cats = $('wiki-cats'); cats.innerHTML = '';
  WIKI_ORDER.forEach(function(cat){
    var items = wikiItems(cat); if (!items.length) return; total += items.length;
    var card = document.createElement('button'); card.type='button'; card.className='wiki-category-card';
    card.innerHTML='<span class="wiki-category-index">'+String(cats.children.length+1).padStart(2,'0')+'</span><strong>'+esc(WIKI_LABELS[cat]||cat)+'</strong><span>'+items.length+' 条条目</span><i>浏览</i>';
    card.onclick=function(){ openWikiCatalogue(cat); }; cats.appendChild(card);
  });
  $('wiki-total-count').textContent = total + ' 条已收录条目';
  var quick=['方源','春秋蝉','天庭','逆流河']; var shortcuts=$('wiki-shortcuts'); shortcuts.innerHTML='';
  quick.forEach(function(q){ var b=document.createElement('button'); b.type='button'; b.textContent=q; b.onclick=function(){ $('wiki-search').value=q; searchWiki(q); }; shortcuts.appendChild(b); });
  renderWikiFeatures();
}
function renderWikiFeatures(){
  var all=[]; WIKI_ORDER.forEach(function(cat){ wikiItems(cat).forEach(function(e){ all.push({entry:e,cat:cat}); }); });
  var box=$('wiki-feature-list'); box.innerHTML=''; if(!all.length)return;
  for(var i=0;i<3;i++){ var item=all[(WIKI_FEATURE_SEED*7+i*137)%all.length]; box.appendChild(wikiCard(item.entry,item.cat,true)); }
}
function openWikiCatalogue(cat, sub){
  WIKI_CAT=cat; WIKI_SUB=sub||''; $('wiki-mini-search').value=''; renderWikiCatalogue(); wikiShow('results');
}
function renderWikiCatalogue(){
  var visible=wikiItems(WIKI_CAT).filter(function(e){return !WIKI_SUB || (e.sub||'其他')===WIKI_SUB;}).map(function(e){return {entry:e,cat:WIKI_CAT};});
  WIKI_VISIBLE=visible; $('wiki-results-overline').textContent='CATALOGUE · '+(WIKI_LABELS[WIKI_CAT]||WIKI_CAT); $('wiki-result-title').textContent=WIKI_LABELS[WIKI_CAT]||WIKI_CAT; $('wiki-result-count').textContent=visible.length+' 条条目';
  var subs=$('wiki-subs'); subs.innerHTML=''; if(WIKI_CAT==='蛊虫'){
    var order=['','一转','二转','三转','四转','五转','六转','七转','八转','九转','仙蛊','其他'];
    order.forEach(function(v){if(v && !WIKI_SUBS[v])return; var b=document.createElement('button');b.type='button';b.className='wiki-filter'+(WIKI_SUB===v?' active':'');b.textContent=v||'全部';b.onclick=function(){WIKI_SUB=v;renderWikiCatalogue();};subs.appendChild(b);});
  }
  var box=$('wiki-list'); box.innerHTML=''; visible.forEach(function(item){box.appendChild(wikiCard(item.entry,item.cat,false));});
}
function searchWiki(raw){
  var q=String(raw||'').trim(); if(!q){ renderWikiHome(); return; }
  $('wiki-mini-search').value=q; $('wiki-results-overline').textContent='SEARCH RESULTS'; $('wiki-result-title').textContent='“'+q+'” 的搜索结果';
  var found=[]; WIKI_ORDER.forEach(function(cat){wikiItems(cat).forEach(function(e){if(e.name.indexOf(q)>=0||(e.desc||'').indexOf(q)>=0)found.push({entry:e,cat:cat});});});
  found.sort(function(a,b){return (a.entry.name===q?-1:0)-(b.entry.name===q?-1:0);}); WIKI_VISIBLE=found.slice(0,300); $('wiki-result-count').textContent='找到 '+WIKI_VISIBLE.length+' 条匹配条目'; $('wiki-subs').innerHTML='';
  var box=$('wiki-list');box.innerHTML=''; WIKI_VISIBLE.forEach(function(item){box.appendChild(wikiCard(item.entry,item.cat,false));}); if(!WIKI_VISIBLE.length) box.innerHTML='<div class="empty">没有找到相关条目，请换一个关键词。</div>'; wikiShow('results');
}
function openWikiEntry(e,cat){ var index=WIKI_VISIBLE.findIndex(function(item){return item.entry===e&&item.cat===cat;}); renderWikiDetail(e,cat,index); wikiShow('detail'); }
function renderWikiDetail(e, cat, index){
  cat=cat||WIKI_CAT; if(typeof index!=='number')index=WIKI_VISIBLE.findIndex(function(item){return item.entry===e&&item.cat===cat;}); WIKI_CURRENT={key:wikiEntryKey(e,cat),entry:e,cat:cat};
  var paragraphs=wikiParagraphs(e.desc),lead=paragraphs.shift()||'暂无条目摘要。',body=paragraphs.map(function(p){return '<p>'+esc(p)+'</p>';}).join(''); var sub=e.sub&&e.sub!=='其他'?'<div><dt>细分</dt><dd>'+esc(e.sub)+'</dd></div>':'';
  var prev=index>0?WIKI_VISIBLE[index-1]:null,next=index>=0&&index<WIKI_VISIBLE.length-1?WIKI_VISIBLE[index+1]:null;
  $('wiki-detail').innerHTML='<div class="wiki-article-shell"><div class="wiki-article-tools"><button id="wiki-back-results" type="button">返回目录</button><span>'+esc(WIKI_LABELS[cat]||cat)+' · 条目</span></div><header class="wiki-article-head"><div class="wiki-eyebrow">'+esc(e.section||cat)+'</div><h1 class="wiki-detail-name">'+esc(e.name)+'</h1><div class="wiki-byline">蛊箓百科 · 设定资料归档</div></header><div class="wiki-article-grid"><div class="wiki-article-copy"><p class="wiki-lead">'+esc(lead)+'</p>'+(body?'<section class="wiki-section"><h2>概述</h2>'+body+'</section>':'')+'<section class="wiki-section wiki-source"><h2>资料来源</h2><p>本条目整理自「'+esc(e.section||cat)+'」资料库。</p></section></div><aside class="wiki-infobox"><div class="wiki-infobox-title">条目信息</div><dl><div><dt>名称</dt><dd>'+esc(e.name)+'</dd></div><div><dt>分类</dt><dd>'+esc(WIKI_LABELS[cat]||cat)+'</dd></div>'+sub+'<div><dt>来源</dt><dd>'+esc(e.section||cat)+'</dd></div></dl><button class="btn btn-ghost wiki-ask" id="wiki-ask-btn">向 AI 询问此条目</button></aside></div><nav class="wiki-neighbors">'+(prev?'<button type="button" data-wiki-nav="prev"><span>上一篇</span>'+esc(prev.entry.name)+'</button>':'<span></span>')+(next?'<button type="button" data-wiki-nav="next"><span>下一篇</span>'+esc(next.entry.name)+'</button>':'<span></span>')+'</nav></div>';
  $('wiki-back-results').onclick=function(){wikiShow('results');};$('wiki-ask-btn').onclick=function(){askAbout(e.name);};var p=document.querySelector('[data-wiki-nav="prev"]'),n=document.querySelector('[data-wiki-nav="next"]');if(p)p.onclick=function(){openWikiEntry(prev.entry,prev.cat);};if(n)n.onclick=function(){openWikiEntry(next.entry,next.cat);};$('wiki-detail').scrollTop=0;
}
/* app.js already listens for live input and calls renderWikiList; retain that hook for this new screen. */
function renderWikiList(){ searchWiki($('wiki-search').value); }
$('wiki-search-form').addEventListener('submit',function(e){e.preventDefault();searchWiki($('wiki-search').value);});$('wiki-mini-search-form').addEventListener('submit',function(e){e.preventDefault();searchWiki($('wiki-mini-search').value);});$('wiki-back-home').onclick=function(){renderWikiHome();};$('wiki-refresh-feature').onclick=function(){WIKI_FEATURE_SEED++;renderWikiFeatures();};
