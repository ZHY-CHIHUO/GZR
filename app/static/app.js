var HEALTH = null;
var LIB = null;
var CUR_VOL = null;
var CUR_CH = 0;
var HISTORY = [];   // 多轮对话上下文
var MODELS = [];    // 检索模型选项

function $(id){ return document.getElementById(id); }
function esc(s){ return String(s).replace(/[&<>]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]; }); }
function toast(msg){ var t=$('toast'); t.textContent=msg; t.classList.add('show'); clearTimeout(t._h); t._h=setTimeout(function(){ t.classList.remove('show'); }, 2600); }
function closeModal(id){ $(id).classList.remove('show'); }
/* 轻量 Markdown 渲染（先转义保证安全，再处理标记） */
function mdRender(text){
  var s = esc(text);
  // 删除回答末尾的"依据来源：[N]"标号行（下方已直接列出引用片段）
  s = s.replace(/^依据来源[：:][\[\]\d\s、，]*$/gm, '');
  s = s.replace(/~~~([\s\S]*?)~~~/g, '<pre>$1</pre>');
  s = s.replace(/```([\s\S]*?)```/g, '<pre>$1</pre>');
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/\*([^*]+)\*/g, '<i>$1</i>');
  // 行级解析：字段标题 / 列表 / 段落，空行只作分隔不产生空白
  var lines = s.split('\n');
  var out = [], inUl = false, inOl = false;
  lines.forEach(function(ln){
    var t = ln.trim();
    if (!t){ if (inUl){ out.push('</ul>'); inUl=false; } if (inOl){ out.push('</ol>'); inOl=false; } return; }
    var ul = t.match(/^[-*]\s+(.*)$/);
    var ol = t.match(/^\d+[.、]\s+(.*)$/);
    if (ul){ if (!inUl){ out.push('<ul>'); inUl=true; } out.push('<li>'+ul[1]+'</li>'); return; }
    if (ol){ if (inUl){ out.push('</ul>'); inUl=false; } if (!inOl){ out.push('<ol>'); inOl=true; } out.push('<li>'+ol[1]+'</li>'); return; }
    if (inUl){ out.push('</ul>'); inUl=false; } if (inOl){ out.push('</ol>'); inOl=false; }
    var m1 = t.match(/^([^：\n]{1,14})：$/);
    if (m1){ out.push('<div class="ans-sec">'+m1[1]+'</div>'); return; }
    var m2 = t.match(/^([^：\n]{1,14})：(.*)$/);
    if (m2 && t.length <= 40 && !/^[-*\d]/.test(t)){ out.push('<div class="ans-line"><span class="ans-sec">'+m2[1]+'</span>：'+m2[2]+'</div>'); return; }
    out.push('<div class="ans-p">'+t+'</div>');
  });
  if (inUl) out.push('</ul>'); if (inOl) out.push('</ol>');
  s = out.join('');
  s = s.replace(/\[(\d{1,2})\]/g, function(m, n){ return '<span class="cite" data-cite="'+n+'" title="点击跳转到对应来源">['+n+']</span>'; });
  return s;
}
document.querySelectorAll('.tab').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('.tab').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    ['chat','read','wiki','game','settings'].forEach(function(t){ $('tab-'+t).hidden = (t !== btn.dataset.tab); });
    if (btn.dataset.tab==='read' && !LIB) loadLibrary();
    if (btn.dataset.tab==='wiki') loadWiki();
  });
});
document.querySelectorAll('.rtab[data-rt]').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('.rtab[data-rt]').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    ['novel','pdf','rz','lore'].forEach(function(t){ $('read-'+t).hidden = (t !== btn.dataset.rt); });
    if ((btn.dataset.rt==='pdf'||btn.dataset.rt==='rz') && !$('read-pdf').dataset.loaded) loadPdfs();
    if (btn.dataset.rt==='lore') loadLore();
  });
});

/* ---------- 状态 ---------- */
function updateStatus(){
  var pill = $('status');
  if (!HEALTH || !HEALTH.ok){ pill.className='pill no'; pill.textContent='服务未连接'; return; }
  if (HEALTH.has_key){ pill.className='pill ok'; pill.textContent='已连接 AI'; }
  else { pill.className='pill no'; pill.textContent='未连接 AI · 去设置'; }
  renderGuide();
}
function renderGuide(){
  var chat = $('chat');
  var exists = !!$('no-key-guide');
  if (HEALTH && HEALTH.ok && !HEALTH.has_key && !exists){
    var d = document.createElement('div');
    d.id='no-key-guide'; d.className='hint-bot';
    d.innerHTML = '🔌 还没连接 AI：现在只能看到「检索结果」，不能生成回答。' +
      '<button onclick="switchTab(\'settings\')">去设置连接 AI</button>';
    chat.insertBefore(d, chat.firstChild);
  }
  if (HEALTH && HEALTH.ok && HEALTH.has_key && exists){ var g=$('no-key-guide'); if(g) g.remove(); }
}
function stripSec(t){ return String(t||'').replace(/^第[零一二三四五六七八九十百0-9两]+节[：:]\s*/, ''); }
function toggleToc(){
  var t = $('novel-toc');
  t.classList.toggle('collapsed');
  var btn = t.querySelector('.toc-fold');
  btn.textContent = t.classList.contains('collapsed') ? '»' : '«';
}
function toggleLoreToc(){
  var t = $('lore-toc');
  t.classList.toggle('collapsed');
  var btn = t.querySelector('.toc-fold');
  btn.textContent = t.classList.contains('collapsed') ? '»' : '«';
}
function scrollToLore(anchor){
  var el = document.getElementById(anchor);
  if (el) el.scrollIntoView({behavior:'smooth', block:'start'});
}
$('lore-toc').querySelector('.toc-body').addEventListener('click', function(ev){
  var el = ev.target;
  if (el.classList && el.classList.contains('toc-link')){
    ev.preventDefault();
    ev.stopPropagation();
    var a = el.getAttribute('data-anchor');
    if (a) scrollToLore(a);
  }
});
$('read-novel').querySelector('.toc-body').addEventListener('click', function(ev){
  var el = ev.target;
  if (el.classList && el.classList.contains('toc-link') && el.getAttribute('data-vol')){
    ev.preventDefault();
    ev.stopPropagation();
    showChapter(el.getAttribute('data-vol'), parseInt(el.getAttribute('data-ch'), 10));
  }
});
function switchTab(name){
  document.querySelectorAll('.tab').forEach(function(b){ b.classList.toggle('active', b.dataset.tab===name); });
  ['chat','read','wiki','game','settings'].forEach(function(t){ $('tab-'+t).hidden = (t !== name); });
  if (name==='read' && !LIB) loadLibrary();
  if (name==='wiki') loadWiki();
}
async function refreshHealth(){
  try { HEALTH = await (await fetch('/api/health')).json(); }
  catch(e){ HEALTH = null; }
  updateStatus();
  if (HEALTH && HEALTH.ok){
    $('api-key').value = HEALTH.has_key ? 'sk-已配置（留空则不改动）' : '';
    $('model').value = HEALTH.model || 'deepseek-chat';
  }
}

/* ---------- 问答 ---------- */
var SUGGEST = ['白玉蛊是怎么炼成的','十大尊者都有谁','方源为什么能重生','监天塔是什么','幽魂魔尊是什么人','春秋蝉有什么用'];
var CHARS = ['方源','白凝冰','古月方正','凤九歌','武庸','龙公','星宿仙尊','巨阳仙尊','幽魂魔尊','狂蛮魔尊','盗天魔尊','乐土仙尊'];
function renderSuggest(){
  var box = $('suggest');
  var t1 = document.createElement('div'); t1.className='suggest-label';
  t1.textContent = '试试问：';
  box.appendChild(t1);
  SUGGEST.forEach(function(s){
    var c = document.createElement('span');
    c.className='chip'; c.textContent='💡 '+s;
    c.onclick = function(){ $('q').value=s; ask(); };
    box.appendChild(c);
  });
  var t2 = document.createElement('div'); t2.className='suggest-label suggest-label-spaced';
  t2.textContent = '👤 角色速查（点击提问）：';
  box.appendChild(t2);
  CHARS.forEach(function(name){
    var c = document.createElement('span');
    c.className='chip'; c.textContent=name;
    c.onclick = function(){ $('q').value='介绍一下'+name+'：他/她是谁，有什么经历和特点'; ask(); };
    box.appendChild(c);
  });
}
function addMsg(html, cls, cid){
  var d = document.createElement('div'); d.className='msg '+cls; d.innerHTML = html;
  if (cid) d.dataset.cid = cid;
  $('chat').appendChild(d); $('chat').scrollTop = $('chat').scrollHeight;
  saveChat();
  return d;
}
function saveChat(){
  var msgs = [];
  document.querySelectorAll('#chat .msg').forEach(function(m){
    if (m.id === 'no-key-guide') return;
    if (m.textContent.trim() === '思考中…') return;
    msgs.push({cls: m.className.replace('msg ',''), html: m.innerHTML, cid: m.dataset.cid || null});
  });
  if (msgs.length > 40) msgs = msgs.slice(-40);
  try { localStorage.setItem('gzr.chat', JSON.stringify(msgs)); } catch(e){}
  try { localStorage.setItem('gzr.chatHistory', JSON.stringify(HISTORY)); } catch(e){}
}
function loadChat(){
  try {
    var msgs = JSON.parse(localStorage.getItem('gzr.chat') || '[]');
    var hist = JSON.parse(localStorage.getItem('gzr.chatHistory') || '[]');
    if (hist && hist.length) HISTORY = hist;
    if (msgs.length){
      $('chat').innerHTML = '';
      msgs.forEach(function(m){
        var d = document.createElement('div');
        d.className = 'msg ' + m.cls;
        d.innerHTML = m.html;
        if (m.cid) d.dataset.cid = m.cid;
        $('chat').appendChild(d);
      });
      $('chat').scrollTop = $('chat').scrollHeight;
    }
  } catch(e){}
}
function attrEsc(s){ return String(s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function renderSources(sources){
  if (!sources || !sources.length) return '';
  var html = '';
  sources.forEach(function(s){
    html += '<div class="src-card">' +
      '<div class="src-head"><span class="src-label">'+esc(s.label)+'</span>' +
      (s.type==='lore'
        ? '<button class="src-btn" data-act="lore-read" data-sec="'+attrEsc(s.title||s.section||'')+'">📖 阅读原文</button>'
        : '<button class="src-btn" data-act="read" data-vol="'+attrEsc(s.vol)+'" data-ch="'+s.chapter+'">📖 阅读原文</button>') +
      '</div></div>';
  });
  return html;
}
async function ask(){
  var question = $('q').value.trim(); if (!question) return;
  $('q').value=''; $('send').disabled = true;
  HISTORY.push({role:'user', content: question});
  addMsg(esc(question), 'user', String(Date.now()));
  renderChatNavList();
  var d = addMsg('思考中…', 'bot');
  try {
    var r = await fetch('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({question: question, scope: $('scope').value, history: HISTORY.slice(0, -1)})});
    var j = await r.json();
    if (j.error){ d.textContent = '出错了：' + j.error; return; }
    var body = mdRender(j.answer);
    if (j.mock){ body += '<br><br><span style="color:#8a8577">（当前为检索测试模式——配置 API Key 后可生成真正的 AI 回答）</span>'; }
    var cost = j.mock ? '' : '<div class="meta">本次约 ¥'+j.cost_rmb+'</div>';
    // 只显示回答中实际引用的来源（[1][2][3]），未引用的不展示
    var cited = [];
    (String(j.answer).match(/\[(\d{1,2})\]/g) || []).forEach(function(rf){
      var n = parseInt(rf.slice(1, -1), 10);
      if (cited.indexOf(n) < 0) cited.push(n);
    });
    var all = j.sources || [];
    var shown = cited.length ? cited.map(function(n){ return all[n - 1]; }).filter(Boolean) : all;
    d.innerHTML = body + renderSources(shown) + cost;
    HISTORY.push({role:'assistant', content: j.answer});
  } catch(e){ d.textContent = '请求失败：'+e.message; }
  finally { $('send').disabled = false; $('q').focus(); saveChat(); }
}
$('send').onclick = ask;
$('q').addEventListener('keydown', function(e){ if (e.key==='Enter') ask(); });

/* ---------- 来源按钮事件委托 + 引用编号跳转 ---------- */
$('chat').addEventListener('click', function(ev){
  var el = ev.target;
  if (el.classList && el.classList.contains('cite')){
    var n = parseInt(el.dataset.cite, 10);
    // 只在本条消息内查找对应来源（避免跳去上一条回答）
    var msg = el.closest('.msg');
    var cards = msg ? msg.querySelectorAll('.src-card') : [];
    var card = cards[n - 1];
    if (card){
      card.scrollIntoView({behavior:'smooth', block:'center'});
      card.classList.add('flash');
      setTimeout(function(){ card.classList.remove('flash'); }, 2000);
    }
    return;
  }
  var btn = el.closest ? el.closest('.src-btn') : null;
  if (!btn) return;
  if (btn.dataset.act === 'read'){
    gotoNovelChapter(btn.dataset.vol, parseInt(btn.dataset.ch, 10));
  }
  else if (btn.dataset.act === 'lore-read'){
    gotoLoreSection(btn.dataset.sec);
  }
});

/* ---------- 来源 → 跳转阅读模块 ---------- */
function switchReadTab(rt){
  document.querySelectorAll('.rtab[data-rt]').forEach(function(b){ b.classList.toggle('active', b.dataset.rt === rt); });
  ['novel','pdf','rz','lore'].forEach(function(t){ $('read-'+t).hidden = (t !== rt); });
}
function gotoNovelChapter(vol, ch){
  switchTab('read');
  switchReadTab('novel');
  var go = function(){ showChapter(vol, ch); };
  if (!LIB){ loadLibrary().then(go); } else { go(); }
}
function gotoLoreSection(section){
  switchTab('read');
  switchReadTab('lore');
  loadLore().then(function(){
    var found = null;
    (LORE_DATA.toc || []).forEach(function(t){ if (!found && t.text === section) found = t; });
    if (found){ setTimeout(function(){ scrollToLore(found.anchor); }, 350); }
  });
}
/* ---------- 来源 → 定位原文 ---------- */
async function readChapter(vol, ch, excerptHint){
  try {
    var r = await fetch('/api/chapter?vol='+encodeURIComponent(vol)+'&chapter='+ch);
    if (!r.ok){ toast('未找到该章节'); return; }
    var j = await r.json();
    $('cm-title').textContent = vol + ' · 第' + (ch||'序') + '章 · ' + stripSec(j.title);
    var paras = (j.text||'').split('\n').filter(function(x){ return x.trim(); });
    var html = paras.map(function(p){ return '<p>'+esc(p)+'</p>'; }).join('');
    var box = $('cm-text'); box.innerHTML = html;
    if (excerptHint){
      var probe = excerptHint.slice(0, 24);
      var idx = (j.text||'').indexOf(probe);
      if (idx >= 0){
        // 定位到引用片段附近（不做高亮）
        var ps = box.querySelectorAll('p');
        var acc = 0;
        for (var i=0;i<ps.length;i++){
          acc += ps[i].textContent.length + 1;
          if (acc > idx){ box.scrollTop = Math.max(0, ps[i].offsetTop - 60); break; }
        }
      }
    }
    $('chapter-modal').classList.add('show');
  } catch(e){ toast('加载失败：'+e.message); }
}

async function readLore(section){
  try {
    var r = await fetch('/api/lore/entry?section=' + encodeURIComponent(section));
    if (!r.ok){ toast('未找到该小节'); return; }
    var j = await r.json();
    $('cm-title').textContent = '设定集《' + section + '》';
    var paras = (j.text||'').split('\n').filter(function(x){ return x.trim(); });
    $('cm-text').innerHTML = paras.map(function(p){ return '<p>'+esc(p)+'</p>'; }).join('');
    $('cm-text').scrollTop = 0;
    $('chapter-modal').classList.add('show');
  } catch(e){ toast('加载失败：'+e.message); }
}
async function locateFile(vol, ch){
  try {
    var r = await fetch('/api/locate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({vol: vol, chapter: ch})});
    var j = await r.json();
    if (j.ok){ toast('已用默认程序打开：' + j.path); }
    else { toast('打开失败：' + (j.error||'文件不存在')); }
  } catch(e){ toast('定位失败：'+e.message); }
}

/* ---------- 阅读库 ---------- */
async function loadLibrary(){
  try {
    var j = await (await fetch('/api/library')).json();
    LIB = j;
    var toc = $('read-novel').querySelector('.toc-body');
    toc.innerHTML = '';
    j.volumes.forEach(function(v){
      var det = document.createElement('details');
      det.className = 'toc-node lv1';
      var sum = document.createElement('summary');
      var s = document.createElement('span');
      s.className = 'toc-link';
      s.textContent = v.name + '（' + v.chapters.length + ' 章）';
      sum.appendChild(s);
      det.appendChild(sum);
      var list = document.createElement('div');
      list.className = 'toc-children';
      // 每 20 章一个分组
      for (var gi = 0; gi < v.chapters.length; gi += 20){
        var chunk = v.chapters.slice(gi, gi + 20);
        var grp = document.createElement('details');
        grp.className = 'toc-node lv2';
        var gsum = document.createElement('summary');
        var gs = document.createElement('span');
        gs.className = 'toc-link';
        gs.textContent = '第' + (chunk[0].n || 1) + '~' + (chunk[chunk.length - 1].n || '') + '章';
        gsum.appendChild(gs);
        grp.appendChild(gsum);
        var glist = document.createElement('div');
        glist.className = 'toc-children';
        chunk.forEach(function(c){
          var it = document.createElement('div');
          it.className = 'toc-leaf';
          var dot = document.createElement('span');
          dot.className = 'toc-dot';
          var link = document.createElement('span');
          link.className = 'toc-link';
          link.textContent = (c.n ? ('第'+c.n+'章 · ') : '') + stripSec(c.title);
          link.setAttribute('data-vol', v.name);
          link.setAttribute('data-ch', c.n);
          it.appendChild(dot);
          it.appendChild(link);
          glist.appendChild(it);
        });
        grp.appendChild(glist);
        list.appendChild(grp);
      }
      det.appendChild(list);
      toc.appendChild(det);
    });
    renderPdfLists(j.pdfs);
  } catch(e){ toast('阅读库加载失败：'+e.message); }
}
async function showChapter(vol, ch){
  CUR_VOL = vol; CUR_CH = ch;
  try {
    var j = await (await fetch('/api/chapter?vol='+encodeURIComponent(vol)+'&chapter='+ch)).json();
    var pane = $('read-novel').querySelector('.text-pane');
    var paras = (j.text||'').split('\n').filter(function(x){ return x.trim(); });
    var title = (ch ? '第'+ch+'章 · ' : '序 · ') + stripSec(j.title);
    var html = '<div class="ch-title">'+esc(vol)+' · '+esc(title)+'</div>';
    html += paras.map(function(p){ return '<p>'+esc(p)+'</p>'; }).join('');
    var nav = '<div class="ch-nav"><button id="ch-prev">← 上一章</button><button id="ch-next">下一章 →</button></div>';
    pane.innerHTML = html + nav; pane.scrollTop = 0;
    $('ch-prev').onclick = function(){ stepChapter(-1); };
    $('ch-next').onclick = function(){ stepChapter(1); };
    // 目录高亮当前章
    document.querySelectorAll('#read-novel .toc-leaf .toc-link').forEach(function(it){ it.classList.remove('cur'); });
    var list = $('read-novel').querySelectorAll('.toc-node');
    for (var i=0;i<list.length;i++){
      if (list[i].textContent.indexOf(vol)===0){
        list[i].open = true;
        var items = list[i].querySelectorAll('.toc-leaf .toc-link');
        var target = items[ch-1];
        if (target){
          target.classList.add('cur');
          var grp = target.closest('.toc-node');
          if (grp) grp.open = true;  // 展开当前章所在分组
        }
        break;
      }
    }
  } catch(e){ toast('章节加载失败：'+e.message); }
}
function stepChapter(delta){
  if (!LIB || !CUR_VOL) return;
  var vols = LIB.volumes.filter(function(v){ return v.name===CUR_VOL; });
  if (!vols.length) return;
  var chs = vols[0].chapters;
  var idx = chs.findIndex(function(c){ return c.n===CUR_CH; });
  var next = chs[idx+delta];
  if (next) showChapter(CUR_VOL, next.n);
  else toast(delta>0 ? '已是本卷最后一章' : '已是本卷第一章');
}
var PDF_CACHE = {};
var PDF_CHS = [], RZ_CHS = [];
var CUR_CHS = {idx: -1, key: '', pane: null};
function initPdfJs(){
  if (window.pdfjsLib && !window.pdfjsLib.GlobalWorkerOptions.workerSrc){
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdfjs/pdf.worker.min.js';
  }
}
function getDoc(url){
  if (!PDF_CACHE[url]) PDF_CACHE[url] = window.pdfjsLib.getDocument(url).promise;
  return PDF_CACHE[url];
}
function renderPdfList(pdf, chs, chsKey){
  var toc = pdf.toc || [];
  if (!toc.length){
    chs.push({title: pdf.name, url: pdf.url, start: 1, end: 999999});
    return '<div class="toc-leaf"><span class="toc-dot"></span><span class="toc-link" data-idx="'+(chs.length-1)+'" data-chs="'+chsKey+'">'+esc(pdf.name)+'</span></div>';
  }
  var tree = [], stack = [{depth: -1, children: tree}];
  toc.forEach(function(it){
    var node = {title: it.title, page: it.page, depth: it.depth, children: []};
    while (stack.length > 1 && stack[stack.length - 1].depth >= it.depth) stack.pop();
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  });
  var leaves = [];
  (function collect(n){ if (n.children.length){ n.children.forEach(collect); } else { leaves.push(n); } })(stack[0]);
  leaves.forEach(function(n, i){
    n.idx = chs.length;
    // 允许重叠：包含下一章起始页（两章同页/紧邻时内容不丢），且保证 end >= start
    var end = (i < leaves.length - 1) ? Math.max(leaves[i].page || 1, leaves[i + 1].page || 1) : 999999;
    chs.push({title: n.title, url: pdf.url, start: n.page || 1, end: end});
  });
  (function assign(n){ if (n.children.length){ n.children.forEach(assign); n.idx = n.children[0].idx; } })(stack[0]);
  function renderNode(n){
    var link = '<span class="toc-link" data-idx="'+n.idx+'" data-chs="'+chsKey+'">'+esc(n.title)+'</span>';
    if (n.children.length){
      return '<details class="toc-node"><summary>'+link+'</summary>' +
        '<div class="toc-children">' + n.children.map(renderNode).join('') + '</div></details>';
    }
    return '<div class="toc-leaf"><span class="toc-dot"></span>'+link+'</div>';
  }
  return tree.map(renderNode).join('');
}
function renderChapter(idx, chsKey, pane){
  initPdfJs();
  var chs = chsKey === 'pdf' ? PDF_CHS : RZ_CHS;
  var ch = chs[idx];
  if (!ch) return;
  CUR_CHS = {idx: idx, key: chsKey, pane: pane};
  var view = pane.querySelector('.pdf-view');
  var nav = '<div class="pdf-ch-nav">' +
    '<button onclick="prevChapter()">← 上一章</button>' +
    '<span class="pdf-ch-title">'+esc(ch.title)+'</span>' +
    '<button onclick="nextChapter()">下一章 →</button>' +
    '</div>';
  view.innerHTML = nav + '<div class="pdf-canvas-wrap"></div>' + nav;
  var wrap = view.querySelector('.pdf-canvas-wrap');
  getDoc(ch.url).then(function(doc){
    var start = ch.start;
    var end = Math.min(ch.end, doc.numPages);
    (async function(){
      for (var p = start; p <= end; p++){
        var c = document.createElement('canvas');
        c.className = 'pdf-page-canvas';
        wrap.appendChild(c);
        try {
          var page = await doc.getPage(p);
          var viewport = page.getViewport({scale: 2.5});
          var dpr = window.devicePixelRatio || 1;
          c.width = Math.floor(viewport.width * dpr);
          c.height = Math.floor(viewport.height * dpr);
          c.style.width = '100%';
          c.style.height = 'auto';
          var ctx = c.getContext('2d');
          var tr = dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null;
          await page.render({canvasContext: ctx, viewport: viewport, transform: tr}).promise;
        } catch(e){}
      }
      wrap.scrollTop = 0;
    })();
  }).catch(function(e){ view.innerHTML = '<div class="empty">PDF 加载失败：'+esc(e.message)+'</div>'; });
  pane.querySelectorAll('.toc-link.cur').forEach(function(x){ x.classList.remove('cur'); });
  var target = pane.querySelector('.toc-leaf .toc-link[data-idx="'+idx+'"]');
  if (target) target.classList.add('cur');
}
function prevChapter(){
  var c = CUR_CHS; if (!c.pane) return;
  var chs = c.key === 'pdf' ? PDF_CHS : RZ_CHS;
  if (c.idx > 0) renderChapter(c.idx - 1, c.key, c.pane);
}
function nextChapter(){
  var c = CUR_CHS; if (!c.pane) return;
  var chs = c.key === 'pdf' ? PDF_CHS : RZ_CHS;
  if (c.idx < chs.length - 1) renderChapter(c.idx + 1, c.key, c.pane);
}
function renderPdfLists(pdfs){
  PDF_CHS = [];
  var combined = pdfs.find(function(p){ return p.name.indexOf('1.1') >= 0; }) ||
                 pdfs.find(function(p){ return p.group === '插图版'; });
  var pane = $('read-pdf');
  pane.innerHTML = '<div class="toc-pane" id="pdf-toc-pane">' +
    '<div class="toc-head"><span class="toc-title">📑 目录</span><button class="toc-fold" onclick="togglePdfToc()">«</button></div>' +
    '<div class="toc-body" id="pdf-toc-body"></div></div>' +
    '<div class="text-pane"><div class="pdf-view"><div class="empty">选择左侧章节查看</div></div></div>';
  $('pdf-toc-body').innerHTML = combined ? renderPdfList(combined, PDF_CHS, 'pdf') : '<div class="empty">未找到 PDF</div>';
  RZ_CHS = [];
  var rz = $('read-rz');
  var rzPdf = pdfs.find(function(p){ return p.group === '人祖传'; });
  if (rzPdf){
    rz.innerHTML = '<div class="toc-pane" id="rz-toc-pane">' +
      '<div class="toc-head"><span class="toc-title">📑 目录</span><button class="toc-fold" onclick="toggleRzToc()">«</button></div>' +
      '<div class="toc-body" id="rz-toc-body"></div></div>' +
      '<div class="text-pane"><div class="pdf-view"><div class="empty">选择左侧章节查看</div></div></div>';
    $('rz-toc-body').innerHTML = renderPdfList(rzPdf, RZ_CHS, 'rz');
  } else {
    rz.innerHTML = '<div class="empty">未找到人祖传 PDF</div>';
  }
  pane.dataset.loaded = '1';
  bindPdfTocClick('pdf-toc-body', 'read-pdf', 'pdf');
  bindPdfTocClick('rz-toc-body', 'read-rz', 'rz');
}
function bindPdfTocClick(containerId, paneId, chsKey){
  var el = document.getElementById(containerId);
  if (!el || el.dataset.bound) return;
  el.dataset.bound = '1';
  el.addEventListener('click', function(ev){
    var t = ev.target;
    if (t.classList && t.classList.contains('toc-link')){
      ev.preventDefault();
      ev.stopPropagation();
      var idx = parseInt(t.getAttribute('data-idx'), 10);
      if (!isNaN(idx)) renderChapter(idx, chsKey, document.getElementById(paneId));
    }
  });
}
function togglePdfToc(){ var t=$('pdf-toc-pane'); t.classList.toggle('collapsed'); t.querySelector('.toc-fold').textContent = t.classList.contains('collapsed')?'»':'«'; }
function toggleRzToc(){ var t=$('rz-toc-pane'); t.classList.toggle('collapsed'); t.querySelector('.toc-fold').textContent = t.classList.contains('collapsed')?'»':'«'; }

/* ---------- 设置 ---------- */
function openTutorial(){ $('tutorial-modal').classList.add('show'); }
async function saveAndTest(){
  var key = $('api-key').value.trim();
  var result = $('key-result');
  if (!key || key.indexOf('sk-已配置')===0){ toast('请先粘贴你的 API Key'); return; }
  result.className='result'; result.textContent='正在测试连接…';
  try {
    var t = await (await fetch('/api/settings/test', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({api_key: key})})).json();
    if (t.ok){
      await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({api_key: key})});
      result.className='result ok';
      result.textContent = '✅ 连接成功！可用模型：' + (t.models||[]).join('、');
      refreshHealth();
    } else {
      result.className='result err';
      result.textContent = '❌ 连接失败：' + (t.error||t.message||'未知错误') + '（请检查 Key 是否完整、是否正确复制）';
    }
  } catch(e){ result.className='result err'; result.textContent='❌ 请求出错：'+e.message; }
}
async function clearKey(){
  var result = $('key-result');
  try {
    await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({api_key: ''})});
    $('api-key').value=''; result.className='result'; result.textContent='已清除 API Key';
    refreshHealth();
  } catch(e){ result.textContent='清除失败：'+e.message; }
}
async function saveModel(){
  var m = $('model').value.trim() || 'deepseek-chat';
  await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({model: m})});
  toast('问答模型已设为：' + m);
}
async function loadModels(){
  try {
    var j = await (await fetch('/api/models')).json();
    MODELS = j.options || [];
    var sel = $('embed-model');
    sel.innerHTML = '';
    MODELS.forEach(function(o){
      var opt = document.createElement('option');
      opt.value = o.id;
      opt.textContent = o.label + '（' + o.model.split('/').pop() + '）' +
        (o.hit5 != null ? ' · 正文命中' + Math.round(o.hit5*100) + '%' : '') +
        (o.avg_query_s != null ? ' · ' + o.avg_query_s + 's/问' : '');
      if (o.current) opt.selected = true;
      sel.appendChild(opt);
    });
  } catch(e){ /* 忽略 */ }
}
async function saveEmbedModel(){
  var id = $('embed-model').value;
  var res = $('model-result');
  res.className='result'; res.textContent='正在切换检索模型（加载向量库，约需几秒~半分钟）…';
  try {
    var j = await (await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({embed_model: id})})).json();
    if (j.ok){
      res.className='result ok'; res.textContent='✅ 已切换为：' + j.data_dir + '（'+ j.embed_model +'）';
      toast('检索模型已切换');
      refreshHealth();
    } else { res.className='result err'; res.textContent='❌ 切换失败：' + (j.error||'未知错误'); }
  } catch(e){ res.className='result err'; res.textContent='❌ 请求出错：'+e.message; }
}

/* ---------- 百科 ---------- */
var WIKI = null, WIKI_CAT = '人物', WIKI_SUB = '', WIKI_SUBS = {};
async function loadWiki(){
  if (WIKI) return;
  try {
    WIKI = await (await fetch('/api/wiki')).json();
    // 统计蛊虫子分类分布
    WIKI_SUBS = {};
    (WIKI.categories['蛊虫'] || []).forEach(function(e){ WIKI_SUBS[e.sub || '其他'] = (WIKI_SUBS[e.sub || '其他'] || 0) + 1; });
    renderWikiCats();
  } catch(e){ /* 忽略 */ }
}
function renderWikiCats(){
  var box = $('wiki-cats'); box.innerHTML = '';
  ['人物','蛊虫','势力','仙蛊屋','灾劫','杀招','境界流派'].forEach(function(c){
    var items = WIKI.categories[c];
    if (!items || !items.length) return;
    var b = document.createElement('div');
    b.className = 'wiki-cat' + (c === WIKI_CAT ? ' active' : '');
    b.textContent = c + '（' + items.length + '）';
    b.onclick = function(){
      document.querySelectorAll('.wiki-cat').forEach(function(x){ x.classList.remove('active'); });
      b.classList.add('active'); WIKI_CAT = c; WIKI_SUB = ''; renderWikiSubs(); renderWikiList(c);
    };
    box.appendChild(b);
    // 蛊虫子分类（凡蛊转数 / 仙蛊）
    if (c === '蛊虫'){
      var subBox = document.createElement('div');
      subBox.className = 'wiki-subs'; subBox.id = 'wiki-subs';
      box.appendChild(subBox);
    }
  });
  renderWikiSubs();
  renderWikiList(WIKI_CAT);
}
function renderWikiSubs(){
  var sb = document.getElementById('wiki-subs');
  if (!sb) return;
  sb.innerHTML = '';
  if (WIKI_CAT !== '蛊虫') return;
  var order = ['一转','二转','三转','四转','五转','六转','七转','八转','九转','仙蛊','其他'];
  var add = function(label, val){
    var s = document.createElement('span');
    s.className = 'wiki-sub' + (WIKI_SUB === val ? ' active' : '');
    s.textContent = label;
    s.onclick = function(){
      document.querySelectorAll('.wiki-sub').forEach(function(x){ x.classList.remove('active'); });
      s.classList.add('active'); WIKI_SUB = val; renderWikiList(WIKI_CAT);
    };
    sb.appendChild(s);
  };
  add('全部', '');
  order.forEach(function(o){ if (WIKI_SUBS[o]) add(o + '（' + WIKI_SUBS[o] + '）', o); });
}
function renderWikiList(cat){
  var q = ($('wiki-search').value || '').trim();
  var box = $('wiki-list'); box.innerHTML = '';
  if (q){
    // 全局搜索：所有分类的名称/描述
    var found = [];
    Object.keys(WIKI.categories).forEach(function c2(c){
      (WIKI.categories[c] || []).forEach(function(e){
        if (e.name.indexOf(q) >= 0 || (e.desc || '').indexOf(q) >= 0) found.push({e: e, c: c});
      });
    });
    found.sort(function(a, b){ return (a.e.name === q ? -1 : 0) - (b.e.name === q ? -1 : 0); });
    found.slice(0, 300).forEach(function(f){
      var d = document.createElement('div');
      d.className = 'wiki-item';
      d.innerHTML = '<div class="wiki-item-name">'+esc(f.e.name)+' <span class="wiki-badge">'+esc(f.c)+'</span></div><div class="wiki-item-desc">'+esc((f.e.desc||'').slice(0,50))+'</div>';
      d.onclick = function(){ renderWikiDetail(f.e); };
      box.appendChild(d);
    });
    box.insertAdjacentHTML('afterbegin', '<div class="empty" style="padding:6px">🔍 全局搜到 ' + found.length + ' 条（名称/描述）</div>');
    if (!found.length) box.innerHTML = '<div class="empty">没有匹配条目</div>';
    return;
  }
  var items = (WIKI.categories[cat] || []).filter(function(e){ return !WIKI_SUB || (e.sub || '其他') === WIKI_SUB; });
  items.slice(0, 800).forEach(function(e){
    var d = document.createElement('div');
    d.className = 'wiki-item';
    d.innerHTML = '<div class="wiki-item-name">'+esc(e.name)+'</div><div class="wiki-item-desc">'+esc(e.desc.slice(0,40))+'</div>';
    d.onclick = function(){ renderWikiDetail(e); };
    box.appendChild(d);
  });
  if (!items.length) box.innerHTML = '<div class="empty">无匹配条目</div>';
}
function renderWikiDetail(e){
  $('wiki-detail').innerHTML =
    '<div class="wiki-detail-name">'+esc(e.name)+'</div>' +
    '<div class="wiki-detail-sec">📂 来源：'+esc(e.section)+'</div>' +
    '<div class="wiki-detail-body">'+esc(e.desc)+'</div>' +
    '<button class="btn btn-ghost" id="wiki-ask-btn">💬 问 AI 关于「'+esc(e.name)+'」</button>';
  document.getElementById('wiki-ask-btn').onclick = function(){ askAbout(e.name); };
}
function askAbout(name){
  switchTab('chat');
  $('q').value = '介绍一下' + name;
  ask();
}
$('wiki-search').addEventListener('input', function(){ renderWikiList(WIKI_CAT); });

/* ---------- 游戏：选择题 ---------- */
var QUIZ_QS = [], QUIZ_IDX = 0, QUIZ_RIGHT = 0;
function quizScore(){ return {t: +(localStorage.getItem('gzr.quizTotal')||0), c: +(localStorage.getItem('gzr.quizCorrect')||0)}; }
function updateQuizScore(){
  var s = quizScore();
  $('quiz-score').textContent = '累计 ' + s.c + '/' + s.t;
}
async function startQuiz(){
  var type = $('quiz-type').value;
  $('quiz-body').innerHTML = '<div class="empty">出题中…</div>';
  try {
    var j = await (await fetch('/api/quiz', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({type: type, n: 10})})).json();
    QUIZ_QS = j.questions; QUIZ_IDX = 0; QUIZ_RIGHT = 0;
    renderQuizQ();
  } catch(e){ $('quiz-body').innerHTML = '<div class="empty">出题失败：'+esc(e.message)+'</div>'; }
}
function renderQuizQ(){
  if (QUIZ_IDX >= QUIZ_QS.length){
    var s = quizScore(); localStorage.setItem('gzr.quizTotal', s.t); localStorage.setItem('gzr.quizCorrect', s.c);
    $('quiz-body').innerHTML = '<div class="empty">🎉 本组完成：答对 <b>'+QUIZ_RIGHT+'/'+QUIZ_QS.length+'</b><br><br><button class="btn btn-primary" onclick="startQuiz()">再来一组</button></div>';
    updateQuizScore(); return;
  }
  var q = QUIZ_QS[QUIZ_IDX];
  var html = '<div class="quiz-q">第 '+(QUIZ_IDX+1)+' 题 · '+esc(q.q)+'</div>';
  q.options.forEach(function(opt, i){
    html += '<button class="quiz-opt" onclick="answerQuiz('+i+')">' + esc(opt) + '</button>';
  });
  html += '<div id="quiz-fb"></div>';
  $('quiz-body').innerHTML = html;
}
function answerQuiz(i){
  var q = QUIZ_QS[QUIZ_IDX];
  var right = (i === q.answer);
  if (right) QUIZ_RIGHT++;
  var s = quizScore();
  s.t++; if (right) s.c++;
  localStorage.setItem('gzr.quizTotal', s.t); localStorage.setItem('gzr.quizCorrect', s.c);
  updateQuizScore();
  var fb = $('quiz-fb');
  fb.innerHTML = (right ? '✅ 答对了！' : '❌ 答错了，正确答案：<b>'+esc(q.options[q.answer])+'</b>') +
    '<br><span class="quiz-exp">'+esc(q.explain)+'</span>' +
    '<br><br><button class="btn btn-primary" onclick="renderQuizQ()">'+(QUIZ_IDX < QUIZ_QS.length-1 ? '下一题 →' : '查看成绩')+'</button>';
  document.querySelectorAll('.quiz-opt').forEach(function(b){
    b.disabled = true;
    if (b.textContent === q.options[q.answer]) b.style.borderColor = '#2e7d32'; b.style.borderWidth='2px';
  });
  QUIZ_IDX++;
}

/* ---------- 游戏：猜谜 ---------- */
var RIDDLE = null, RIDDLE_IDX = 0, RIDDLE_TYPE = 'gu', RIDDLE_LABEL = '🐛 猜蛊虫';
function riddleScore(){ return +(localStorage.getItem('gzr.riddleScore')||0); }
function updateRiddleScore(){ $('riddle-score').textContent = '累计 ' + riddleScore() + ' 分'; }
async function newRiddle(){
  $('riddle-body').innerHTML = '<div class="empty">出题中…</div>';
  try {
    var j = await (await fetch('/api/riddle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({type: RIDDLE_TYPE, n: 1})})).json();
    RIDDLE = j.riddles[0]; RIDDLE_IDX = 0;
    renderRiddle();
  } catch(e){ $('riddle-body').innerHTML = '<div class="empty">出题失败：'+esc(e.message)+'</div>'; }
}
function renderRiddle(){
  var html = '<div class="riddle-hints">';
  for (var i=0; i<=RIDDLE_IDX; i++) html += '<div class="riddle-hint">提示'+(i+1)+'：'+esc(RIDDLE.hints[i])+'</div>';
  html += '</div>';
  if (RIDDLE_IDX < 2) html += '<br><button class="btn btn-ghost" onclick="moreHint()">💡 更多提示（-1分）</button>';
  html += '<div class="riddle-ask"><input id="riddle-input" placeholder="输入你的答案…" autocomplete="off"><button class="btn btn-primary" onclick="guessRiddle()">猜！</button></div>';
  html += '<div id="riddle-fb"></div>';
  $('riddle-body').innerHTML = html;
  var inp = $('riddle-input'); if (inp) { inp.focus(); inp.addEventListener('keydown', function(e){ if (e.key==='Enter') guessRiddle(); }); }
}
function moreHint(){
  if (RIDDLE_IDX >= 2) return;
  RIDDLE_IDX++;
  var s = Math.max(0, riddleScore() - 1);
  localStorage.setItem('gzr.riddleScore', s);
  updateRiddleScore();
  renderRiddle();
}
function guessRiddle(){
  var g = ($('riddle-input').value || '').trim();
  var fb = $('riddle-fb');
  if (!g) return;
  var hit = (g === RIDDLE.name || RIDDLE.name.indexOf(g) >= 0 || g.indexOf(RIDDLE.name) >= 0);
  if (hit){
    var pts = [3,2,1][RIDDLE_IDX] || 1;
    localStorage.setItem('gzr.riddleScore', riddleScore() + pts);
    updateRiddleScore();
    fb.innerHTML = '🎉 猜对了！+'+pts+'分　答案：<b>'+esc(RIDDLE.name)+'</b><br><br><button class="btn btn-primary" onclick="newRiddle()">再来一道</button>';
  } else if (RIDDLE_IDX >= 2){
    fb.innerHTML = '😅 没猜中，答案是：<b>'+esc(RIDDLE.name)+'</b><br><br><button class="btn btn-primary" onclick="newRiddle()">再来一道</button>';
  } else {
    fb.innerHTML = '❌ 不对，再想想（可用「更多提示」）';
    moreHint();
  }
}
/* ---------- 资料合集（统一原版两栏 UI） ---------- */
var LORE_DATA = null;
async function loadLore(){
  if (LORE_DATA) return;
  try {
    LORE_DATA = await (await fetch('/api/lore/data')).json();
    renderLore();
  } catch(e){ $('lore-toc').querySelector('.toc-body').innerHTML = '<div class="empty">加载失败</div>'; }
}
function renderLore(){
  // 目录树：扁平 -> 嵌套树 -> 递归渲染（箭头折叠 + 标题跳转分离）
  var tree = [], stack = [{level: 0, children: tree}];
  LORE_DATA.toc.forEach(function(item){
    var node = {text: item.text, level: item.level, anchor: item.anchor, children: []};
    while (stack.length > 1 && stack[stack.length - 1].level >= item.level) stack.pop();
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  });
  function renderNode(n){
    var html = '';
    if (n.children.length){
      html += '<details class="toc-node lv'+n.level+'"><summary><span class="toc-link" data-anchor="'+n.anchor+'">'+esc(n.text)+'</span></summary>' +
        '<div class="toc-children">' + n.children.map(renderNode).join('') + '</div></details>';
    } else {
      html += '<div class="toc-leaf lv'+n.level+'"><span class="toc-dot"></span>' +
        '<span class="toc-link" data-anchor="'+n.anchor+'">'+esc(n.text)+'</span></div>';
    }
    return html;
  }
  var tb = $('lore-toc').querySelector('.toc-body');
  tb.innerHTML = tree.map(renderNode).join('');
  // 正文
  var tp = $('lore-text');
  var b = '<div class="ch-title">'+esc(LORE_DATA.title)+'</div>' +
    '<a class="dl-btn lore-dl" href="/api/lore/download">⬇ 下载 docx 原件</a>';
  LORE_DATA.paras.forEach(function(p){
    if (p.kind === 'h2') b += '<div class="lore-h lore-h'+p.level+'" id="'+p.anchor+'">'+esc(p.text)+'</div>';
    else b += '<div class="lore-p">'+esc(p.text)+'</div>';
  });
  tp.innerHTML = b;
}
/* 游戏子页签 */
document.querySelectorAll('.rtab[data-gt]').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('.rtab').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    var gt = btn.dataset.gt;
    $('game-quiz').hidden = (gt !== 'quiz');
    $('game-riddle').hidden = (gt === 'quiz');
    if (gt !== 'quiz'){
      RIDDLE_TYPE = gt.replace('riddle-', '');
      $('riddle-label').textContent = {'gu':'🐛 猜蛊虫','person':'👤 猜人物','item':'🎁 猜物品'}[RIDDLE_TYPE] || gt;
    }
  });
});

/* ---------- 聊天侧栏：搜索 / 导航 / 删除 / 清空 ---------- */
function toggleChatNavPane(){
  var t = $('chat-nav-pane');
  t.classList.toggle('collapsed');
  var btn = t.querySelector('.toc-fold');
  btn.textContent = t.classList.contains('collapsed') ? '»' : '«';
}
function chatMeta(){ try { return JSON.parse(localStorage.getItem('gzr.chatMeta') || '{}'); } catch(e){ return {}; } }
function saveChatMeta(m){ try { localStorage.setItem('gzr.chatMeta', JSON.stringify(m)); } catch(e){} }
function renderChatNavList(){
  var q = ($('chat-search').value || '').trim();
  var meta = chatMeta();
  var users = document.querySelectorAll('#chat .msg.user');
  var active = [], archived = [];
  users.forEach(function(m, i){
    var cid = m.dataset.cid || ('i' + i);
    var title = (meta[cid] && meta[cid].title) || m.textContent.trim().slice(0, 22);
    if (q && title.indexOf(q) < 0 && m.textContent.indexOf(q) < 0) return;
    var it = {i: i, cid: cid, title: title};
    (meta[cid] && meta[cid].archived ? archived : active).push(it);
  });
  var html = active.map(function(it){ return navItemHtml(it, meta); }).join('');
  if (archived.length){
    html += '<details class="nav-arch"><summary>🗂 已归档（' + archived.length + '）</summary>' +
      archived.map(function(it){ return navItemHtml(it, meta, true); }).join('') + '</details>';
  }
  $('chat-nav-list').innerHTML = html || '<div class="empty" style="padding:12px">暂无记录</div>';
}
function navItemHtml(it, meta, isArch){
  var t = (meta[it.cid] && meta[it.cid].title) || it.title;
  return '<div class="nav-item'+(isArch?' arch':'')+'">' +
    '<span class="nav-q" onclick="scrollToMsg('+it.i+')" title="'+esc(t)+'">'+esc(t)+'</span>' +
    '<button class="nav-more" onclick="navMenu(event, \''+it.cid+'\', '+it.i+')">⋮</button></div>';
}
$('chat-search').addEventListener('input', renderChatNavList);
function scrollToMsg(i){
  var m = document.querySelectorAll('#chat .msg.user')[i];
  if (m) m.scrollIntoView({behavior:'smooth', block:'center'});
}
function delMsg(i){
  var users = document.querySelectorAll('#chat .msg.user');
  var target = users[i];
  if (!target) return;
  var all = Array.prototype.slice.call(document.querySelectorAll('#chat .msg'));
  var ti = all.indexOf(target);
  target.remove();
  if (all[ti + 1] && all[ti + 1].classList.contains('bot')) all[ti + 1].remove();
  saveChat();
  renderChatNavList();
}
var NAV_CTX = {cid: null, i: -1};
function navMenu(ev, cid, i){
  ev.stopPropagation();
  NAV_CTX.cid = cid; NAV_CTX.i = i;
  var m = $('nav-context');
  var r = ev.target.getBoundingClientRect();
  m.style.top = (r.bottom + 4) + 'px';
  m.style.left = Math.max(8, r.right - 90) + 'px';
  m.style.display = 'block';
}
function closeNavMenu(){ $('nav-context').style.display = 'none'; }
document.addEventListener('click', function(ev){ if (!ev.target.closest || !ev.target.closest('.nav-more')) closeNavMenu(); });
function navArchive(){
  var meta = chatMeta();
  meta[NAV_CTX.cid] = meta[NAV_CTX.cid] || {};
  meta[NAV_CTX.cid].archived = !meta[NAV_CTX.cid].archived;
  saveChatMeta(meta);
  renderChatNavList();
  closeNavMenu();
  toast(meta[NAV_CTX.cid].archived ? '已归档' : '已恢复');
}
function navRename(){
  var meta = chatMeta();
  var cur = (meta[NAV_CTX.cid] && meta[NAV_CTX.cid].title) || '';
  var t = prompt('给这条对话命名：', cur);
  if (t === null) { closeNavMenu(); return; }
  meta[NAV_CTX.cid] = meta[NAV_CTX.cid] || {};
  if (t.trim()) meta[NAV_CTX.cid].title = t.trim(); else delete meta[NAV_CTX.cid].title;
  saveChatMeta(meta);
  renderChatNavList();
  closeNavMenu();
}
function navDel(){ delMsg(NAV_CTX.i); closeNavMenu(); }
function clearChat(){
  if (!confirm('确定清空所有聊天记录吗？')) return;
  try { localStorage.removeItem('gzr.chat'); localStorage.removeItem('gzr.chatHistory'); } catch(e){}
  HISTORY = [];
  $('chat').innerHTML = '<div class="msg bot">你好，我是《蛊真人》专属问答助手（本地 RAG，双库：2334 章正文 + 设定合集）。问关于剧情、人物、蛊虫、设定的问题吧，例如「白玉蛊是怎么炼成的」。</div>';
  renderChatNavList();
  toast('已清空聊天记录');
}

/* ---------- 启动 ---------- */
loadChat();
renderChatNavList();
renderSuggest();
refreshHealth();
loadModels();
updateQuizScore();
updateRiddleScore();
