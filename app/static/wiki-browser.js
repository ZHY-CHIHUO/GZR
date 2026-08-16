/* Encyclopedia browser: landing page plus persistent left index and right reading panel. */
var WIKI_ORDER=['作品资料','世界设定','天地秘境','五域地理','人物','蛊虫','势力','仙蛊屋','杀招','灾劫','境界流派','人祖传','名言诗词'];
var WIKI_LABELS={'名言诗词':'名言诗词','作品资料':'作品资料','世界设定':'世界设定','天地秘境':'天地秘境','五域地理':'五域地理','人物':'人物','蛊虫':'蛊虫','势力':'势力','仙蛊屋':'仙蛊屋','杀招':'杀招','灾劫':'灾劫','境界流派':'境界与流派','人祖传':'人祖传'};
function wikiItems(c){return(WIKI&&WIKI.categories&&WIKI.categories[c])||[]}
var WIKI_ALIASES = {};
var WIKI_CURATED_ALIASES = {
  '古月方源':'方源','方媛':'方源','洪亭':'红莲魔尊','本杰孙':'盗天魔尊','冥幽':'幽魂魔尊',
  '曾阿牛':'仇九','耶律瓦':'玉阳子','孙名录':'玄极子','傲骨魔君':'沈桀骜','诗仙':'李小白'
};
function buildWikiAliases(){
  WIKI_ALIASES = {};
  var entryNames = {};
  Object.keys(WIKI.categories || {}).forEach(function(c){
    (WIKI.categories[c] || []).forEach(function(e){ entryNames[e.name] = 1; });
  });
  (WIKI.other || []).forEach(function(e){ entryNames[e.name] = 1; });
  function reg(alias, target){
    if (!alias || !target) return;
    if (entryNames[alias] && entryNames[alias] !== target && WIKI_ALIASES[alias]) return;
    if (!entryNames[alias]) WIKI_ALIASES[alias] = target;
  }
  function addEntry(name, entry){
    // 括号内别名：龙宫（龙庭）-> 龙庭 指向 龙宫（龙庭）
    var m = String(name).match(/^(.*?)[（(]([^（）()]+)[）)]$/);
    if (m){
      var base = m[1].trim(), inner = m[2].trim();
      if (entryNames[base]) reg(base, name);
      reg(inner, name);
    }
    // （前世）/（众）/（新）等后缀：搜 韩立 命中 韩立（前世）
    var m2 = String(name).match(/^(.*?)[（(](前世|众|新|原任)[）)]$/);
    if (m2){
      var b = m2[1].trim();
      if (!entryNames[b]) reg(b, name);
    }
    // 词条自带 aliases 字段
    (entry.aliases || []).forEach(function(a){ reg(a, entry.name); });
  }
  Object.keys(WIKI.categories || {}).forEach(function(c){
    (WIKI.categories[c] || []).forEach(function(e){ addEntry(e.name, e); });
  });
  (WIKI.other || []).forEach(function(e){ addEntry(e.name, e); });
  Object.keys(WIKI_CURATED_ALIASES).forEach(function(a){
    var t = WIKI_CURATED_ALIASES[a];
    if (entryNames[t]) WIKI_ALIASES[a] = t;
  });
}
function resolveWikiName(q){
  return WIKI_ALIASES[q] || q;
}
var WIKI_RECENT_KEY='gzr.wikiRecent';
function wikiRecent(){try{return JSON.parse(localStorage.getItem(WIKI_RECENT_KEY)||'[]')}catch(e){return[]}}
function saveWikiRecent(q){
  q=String(q||'').trim();if(!q)return;
  var list=wikiRecent().filter(function(x){return x!==q});
  list.unshift(q);if(list.length>6)list.length=6;
  try{localStorage.setItem(WIKI_RECENT_KEY,JSON.stringify(list))}catch(e){}
  renderWikiRecent();
}
function clearWikiRecent(){
  localStorage.removeItem(WIKI_RECENT_KEY);
  renderWikiRecent();
  toast('已清除百科最近搜索');
}
function renderWikiRecent(){
  var box=$('wiki-shortcuts');if(!box)return;
  var list=wikiRecent();box.innerHTML='';
  if(!list.length){box.hidden=true;return}
  box.hidden=false;
  var label=document.createElement('span');label.className='wiki-recent-label';label.textContent='最近搜索';box.appendChild(label);
  list.forEach(function(x){var b=document.createElement('button');b.type='button';b.textContent=x;b.onclick=function(){$('wiki-search').value=x;searchWiki(x)};box.appendChild(b)});
  var clear=document.createElement('button');clear.type='button';clear.className='wiki-recent-clear';clear.textContent='清除';clear.onclick=clearWikiRecent;box.appendChild(clear);
}
function wikiShow(v){$('wiki-home').hidden=v!=='home';$('wiki-results').hidden=v!=='browse';$('wiki-browser').dataset.view=v}
function organizeWikiCategories(){var other=(WIKI.other||[]);var specs=[['作品资料',/作品简介|作品目录|作品设定|背景介绍|基本介绍/],['世界设定',/世界观|世界背景|生灵蛊虫异人|异人介绍/],['天地秘境',/天地秘境|人造天地秘境|洞天秘境/],['五域地理',/五域|南疆|北原|中洲|西漠|东海/],['人祖传',/^人祖传|《人祖传》|人祖及十子/]];specs.forEach(function(s){var found=other.filter(function(e){return s[1].test(String(e.section||''))});if(found.length)WIKI.categories[s[0]]=found});}
async function loadWiki(){if(WIKI){renderWikiHome();return}try{var r=await fetch('/api/wiki');if(!r.ok)throw Error();WIKI=await r.json();organizeWikiCategories();buildWikiAliases();WIKI_SUBS={};wikiItems('蛊虫').forEach(function(e){var k=e.sub||'其他';WIKI_SUBS[k]=(WIKI_SUBS[k]||0)+1});renderWikiHome()}catch(e){$('wiki-home-body').innerHTML='<div class="empty">百科数据暂时无法加载</div>'}}
function renderWikiHome(){if(!WIKI)return;wikiShow('home');var cats=$('wiki-cats');cats.innerHTML='';var total=0;WIKI_ORDER.forEach(function(c){var a=wikiItems(c);if(!a.length)return;total+=a.length;var b=document.createElement('button');b.type='button';b.className='wiki-category-card';b.innerHTML='<span class="wiki-category-index">'+String(cats.children.length+1).padStart(2,'0')+'</span><strong>'+esc(WIKI_LABELS[c]||c)+'</strong><span>'+a.length+' 条条目</span><i>浏览</i><span class="wiki-card-mark">'+esc((WIKI_LABELS[c]||c).charAt(0))+'</span>';b.onclick=function(){openCatalogue(c)};cats.appendChild(b)});$('wiki-total-count').textContent=total+' 条已收录条目';renderWikiRecent()}
function openCatalogue(c,sub){WIKI_CAT=c;WIKI_SUB=sub||'';$('wiki-mini-search').value='';renderCatalogue();wikiShow('browse')}
function renderCatalogue(){var vis=wikiItems(WIKI_CAT).filter(function(e){return!WIKI_SUB||(e.sub||'其他')===WIKI_SUB}).map(function(e){return{entry:e,cat:WIKI_CAT}});WIKI_VISIBLE=vis;$('wiki-results-overline').textContent='CATALOGUE · '+(WIKI_LABELS[WIKI_CAT]||WIKI_CAT);$('wiki-result-title').textContent=WIKI_LABELS[WIKI_CAT]||WIKI_CAT;$('wiki-result-count').textContent=vis.length+' 条条目';renderFilters();renderIndex(true)}
function renderFilters(){var box=$('wiki-subs');box.innerHTML='';if(WIKI_CAT!=='蛊虫')return;['','一转','二转','三转','四转','五转','六转','七转','八转','九转','仙蛊','其他'].forEach(function(v){if(v&&!WIKI_SUBS[v])return;var b=document.createElement('button');b.type='button';b.className='wiki-filter'+(WIKI_SUB===v?' active':'');b.textContent=v||'全部';b.onclick=function(){WIKI_SUB=v;renderCatalogue()};box.appendChild(b)})}
function renderIndex(selectFirst){var box=$('wiki-list');box.innerHTML='';WIKI_VISIBLE.forEach(function(x,i){var b=document.createElement('button');b.type='button';b.className='wiki-index-item';b.dataset.key=wikiEntryKey(x.entry,x.cat);b.innerHTML='<strong>'+esc(x.entry.name)+'</strong><span>'+esc(WIKI_LABELS[x.cat]||x.cat)+'</span>';b.onclick=function(){renderDetail(x.entry,x.cat,i)};box.appendChild(b)});if(!WIKI_VISIBLE.length){box.innerHTML='<div class="empty">没有匹配条目</div>';$('wiki-detail').innerHTML='<div class="empty">尝试其他分类或搜索词</div>';return}var idx=WIKI_VISIBLE.findIndex(function(x){return WIKI_CURRENT&&wikiEntryKey(x.entry,x.cat)===WIKI_CURRENT.key});if(selectFirst||idx<0)renderDetail(WIKI_VISIBLE[0].entry,WIKI_VISIBLE[0].cat,0);else setIndex(WIKI_CURRENT.key)}
function setIndex(k){document.querySelectorAll('.wiki-index-item').forEach(function(b){b.classList.toggle('active',b.dataset.key===k)})}
function searchWiki(raw){var rawQ=String(raw||'').trim();if(!rawQ){renderWikiHome();return}saveWikiRecent(rawQ);var q=resolveWikiName(rawQ);var found=[];Object.keys(WIKI.categories||{}).forEach(function(c){wikiItems(c).forEach(function(e){var al=(e.aliases||[]).join(' ');if(String(e.name||'').indexOf(q)>=0||al.indexOf(rawQ)>=0||al.indexOf(q)>=0||String(e.desc||'').indexOf(q)>=0||String(e.desc||'').indexOf(rawQ)>=0)found.push({entry:e,cat:c})})});found.sort(function(a,b){return(a.entry.name===q?-1:0)-(b.entry.name===q?-1:0)});WIKI_VISIBLE=found.slice(0,300);$('wiki-mini-search').value=q;$('wiki-results-overline').textContent='SEARCH RESULTS';$('wiki-result-title').textContent='“'+q+'” 的搜索结果';$('wiki-result-count').textContent='找到 '+WIKI_VISIBLE.length+' 条匹配条目';$('wiki-subs').innerHTML='';renderIndex(true);wikiShow('browse')}
function openEntry(e,c){var i=WIKI_VISIBLE.findIndex(function(x){return x.entry===e&&x.cat===c});renderDetail(e,c,i);wikiShow('browse')}
function openCatalogueAt(c,e){WIKI_CAT=c;WIKI_SUB='';$('wiki-mini-search').value='';var vis=wikiItems(c).filter(function(x){return !WIKI_SUB||(x.sub||'其他')===WIKI_SUB}).map(function(x){return {entry:x,cat:c}});WIKI_VISIBLE=vis;$('wiki-results-overline').textContent='CATALOGUE · '+(WIKI_LABELS[c]||c);$('wiki-result-title').textContent=WIKI_LABELS[c]||c;$('wiki-result-count').textContent=vis.length+' 条条目';renderFilters();var i=vis.findIndex(function(x){return x.entry===e});renderIndex(false);renderDetail(e,c,i);wikiShow('browse')}
function renderDetail(e,c,i){c=c||WIKI_CAT;WIKI_CURRENT={key:wikiEntryKey(e,c),entry:e,cat:c};setIndex(WIKI_CURRENT.key);var ps=(e.desc||'').trim().split(/\n+/).filter(Boolean),body=ps.map(function(p){return'<p>'+esc(p)+'</p>'}).join('');var sub=e.sub&&e.sub!=='其他'?'<div><dt>细分</dt><dd>'+esc(e.sub)+'</dd></div>':'';var als=e.aliases&&e.aliases.length?'<div><dt>别名</dt><dd>'+esc(e.aliases.join('、'))+'</dd></div>':'';var prev=i>0?WIKI_VISIBLE[i-1]:null,next=i>=0&&i<WIKI_VISIBLE.length-1?WIKI_VISIBLE[i+1]:null;$('wiki-detail').innerHTML='<div class="wiki-article-shell"><div class="wiki-article-tools"><button id="wiki-back-results" type="button">返回目录</button><span class="wiki-article-actions"><button id="wiki-add-btn" type="button">新增词条</button><button id="wiki-edit-btn" type="button">编辑条目</button><button id="wiki-del-btn" type="button">删除条目</button></span></div><header class="wiki-article-head"><div class="wiki-eyebrow">'+esc(c)+' · '+esc(e.section||'资料条目')+'</div><h1 class="wiki-detail-name">'+esc(e.name)+'</h1><div class="wiki-byline">蛊箓百科 · 设定资料归档</div></header><div class="wiki-article-grid"><div class="wiki-article-copy">'+(body?body:'<p>暂无条目摘要。</p>')+'<section class="wiki-section wiki-source"><h2>资料来源</h2><p>本条目整理自「'+esc(e.section||c)+'」资料库。</p></section></div><aside class="wiki-infobox"><div class="wiki-infobox-title">条目信息</div><dl><div><dt>名称</dt><dd>'+esc(e.name)+'</dd></div><div><dt>分类</dt><dd>'+esc(WIKI_LABELS[c]||c)+'</dd></div>'+sub+als+'<div><dt>来源</dt><dd>'+esc(e.section||c)+'</dd></div></dl><button class="btn btn-ghost wiki-ask" id="wiki-ask-btn">向 AI 询问此条目</button></aside></div><nav class="wiki-neighbors">'+(prev?'<button data-wiki-nav="prev" type="button"><span>上一篇</span>'+esc(prev.entry.name)+'</button>':'<span></span>')+(next?'<button data-wiki-nav="next" type="button"><span>下一篇</span>'+esc(next.entry.name)+'</button>':'<span></span>')+'</nav></div>';$('wiki-back-results').onclick=function(){wikiShow('results')};$('wiki-add-btn').onclick=function(){openWikiAdd()};$('wiki-edit-btn').onclick=function(){openWikiEdit()};$('wiki-del-btn').onclick=function(){deleteWikiEntry()};$('wiki-ask-btn').onclick=function(){askAbout(e.name)};var p=document.querySelector('[data-wiki-nav="prev"]'),n=document.querySelector('[data-wiki-nav="next"]');if(p)p.onclick=function(){renderDetail(prev.entry,prev.cat,i-1)};if(n)n.onclick=function(){renderDetail(next.entry,next.cat,i+1)};$('wiki-detail').scrollTop=0}
$('wiki-search-form').addEventListener('submit',function(e){e.preventDefault();searchWiki($('wiki-search').value)});$('wiki-mini-search-form').addEventListener('submit',function(e){e.preventDefault();searchWiki($('wiki-mini-search').value)});$('wiki-back-home').onclick=function(){renderWikiHome()};
var WIKI_EDIT=null;
function wikiCatOptions(sel){var opts='';WIKI_ORDER.forEach(function(c){if(wikiItems(c).length)opts+='<option value="'+esc(c)+'">'+esc(WIKI_LABELS[c]||c)+'</option>';});sel.innerHTML=opts;}
function openWikiEdit(){var e=WIKI_CURRENT.entry,c=WIKI_CURRENT.cat;if(!e)return;wikiCatOptions($('we-cat'));$('we-cat').value=c;$('we-name').value=e.name||'';$('we-sub').value=e.sub||'';$('we-section').value=e.section||'';$('we-desc').value=e.desc||'';WIKI_EDIT={cat:c,name:e.name,mode:'edit'};$('we-title').textContent='编辑百科条目';$('wiki-edit-modal').classList.add('show');}
function openWikiAdd(){wikiCatOptions($('we-cat'));$('we-name').value='';$('we-sub').value='';$('we-section').value='';$('we-desc').value='';WIKI_EDIT={mode:'create'};$('we-title').textContent='新增词条';$('wiki-edit-modal').classList.add('show');}
async function saveWikiEntry(){var payload={cat:$('we-cat').value,name:($('we-name').value||'').trim(),sub:($('we-sub').value||'').trim(),section:($('we-section').value||'').trim(),desc:($('we-desc').value||'').trim()};if(WIKI_EDIT.mode!=='create'){payload.oldCat=WIKI_EDIT.cat;payload.oldName=WIKI_EDIT.name;}if(!payload.name||!payload.desc){toast('名称和描述不能为空');return;}var creating=WIKI_EDIT.mode==='create';try{var r=await fetch('/api/wiki/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});var j=await r.json();if(!j.ok)throw new Error(j.error||'保存失败');WIKI=null;WIKI_SUBS={};await loadWiki();var nc=j.cat||payload.cat,nn=payload.name,found=null;(WIKI.categories[nc]||[]).forEach(function(x){if(x.name===nn)found=x;});if(found)openCatalogueAt(nc,found);closeModal('wiki-edit-modal');toast(creating?'已新增词条到资料库':'已保存到资料库');}catch(e){toast('保存失败：'+e.message);}}
async function openWikiByName(name){
  switchTab('wiki');
  if (!WIKI) await loadWiki();
  name = resolveWikiName(name);
  var found = null, cat = null;
  Object.keys(WIKI.categories || {}).forEach(function(c){
    if (found) return;
    (WIKI.categories[c] || []).forEach(function(e){ if (!found && e.name === name){ found = e; cat = c; } });
  });
  if (!found) (WIKI.other || []).forEach(function(e){ if (!found && e.name === name){ found = e; cat = '其他'; } });
  if (found) openCatalogueAt(cat, found);
  else toast('未找到词条：' + name);
}
async function deleteWikiEntry(){if(!confirm('确定删除条目「'+WIKI_CURRENT.entry.name+'」？删除后可在回收站恢复。'))return;try{var r=await fetch('/api/wiki/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete:true,cat:WIKI_CURRENT.cat,name:WIKI_CURRENT.entry.name})});var j=await r.json();if(!j.ok)throw new Error(j.error||'删除失败');WIKI=null;WIKI_SUBS={};await loadWiki();renderWikiHome();toast('已删除，可在回收站恢复');}catch(e){toast('删除失败：'+e.message);}}
async function openWikiTrash(){
  var box=$('wiki-trash-body'); box.innerHTML='<div class="empty">加载中…</div>';
  $('wiki-trash-modal').classList.add('show');
  try{
    var j=await (await fetch('/api/wiki/trash')).json();
    var items=j.items||[];
    if(!items.length){ box.innerHTML='<div class="empty">回收站是空的。</div>'; return; }
    var h='<div class="gh-sec">';
    h+=items.map(function(t){
      var ts=t.deletedAt?new Date(t.deletedAt*1000).toLocaleString('zh-CN',{hour12:false}):'';
      return '<div class="trash-item"><div class="trash-item-main"><b>['+esc(WIKI_LABELS[t.cat]||t.cat)+'] '+esc(t.name)+'</b><span>'+esc(wikiExcerpt(t.desc,60))+'</span><em>删除于 '+esc(ts)+'</em></div><span class="trash-actions"><button class="cq-del" onclick="restoreTrashEntry(\''+attrEsc(t.cat)+'\',\''+attrEsc(t.name)+'\')">恢复</button><button class="cq-del" onclick="purgeTrashEntry(\''+attrEsc(t.cat)+'\',\''+attrEsc(t.name)+'\')">彻底删除</button></span></div>';
    }).join('');
    h+='</div>';
    box.innerHTML=h;
  }catch(e){ box.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>'; }
}
async function restoreTrashEntry(cat,name){
  try{
    var r=await fetch('/api/wiki/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cat:cat,name:name})});
    var j=await r.json();
    if(!j.ok)throw new Error(j.error||'恢复失败');
    WIKI=null;WIKI_SUBS={};await loadWiki();
    var found=null;(WIKI.categories[cat]||[]).forEach(function(x){if(x.name===name)found=x;});
    openWikiTrash();
    if(found)openCatalogueAt(cat,found);
    toast('已恢复：'+name);
  }catch(e){toast('恢复失败：'+e.message);}
}
async function purgeTrashEntry(cat,name){
  if(!confirm('彻底删除「'+name+'」？此操作不可恢复。'))return;
  try{
    var r=await fetch('/api/wiki/trash-purge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cat:cat,name:name})});
    var j=await r.json();
    if(!j.ok)throw new Error(j.error||'删除失败');
    openWikiTrash();
    toast('已彻底删除');
  }catch(e){toast('删除失败：'+e.message);}
}
