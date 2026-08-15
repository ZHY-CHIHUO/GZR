var HEALTH = null;
var LIB = null;
var LIB_LOADING = null;
var PENDING_CHAPTER = null;
var CHAPTER_REQUEST_ID = 0;
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
    switchTab(btn.dataset.tab);
  });
});
document.querySelectorAll('.rtab[data-rt]').forEach(function(btn){
  btn.addEventListener('click', function(){
    switchReadTab(btn.dataset.rt);
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
    d.innerHTML = '还没连接 AI：现在只能看到「检索结果」，不能生成回答。' +
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
    var vol = el.getAttribute('data-vol');
    var ch = parseInt(el.getAttribute('data-ch'), 10);
    PENDING_CHAPTER = {vol: vol, ch: ch};
    showChapter(vol, ch);
  }
});
function switchTab(name){
  document.querySelectorAll('.tab').forEach(function(b){ b.classList.toggle('active', b.dataset.tab===name); });
  ['chat','read','wiki','game','settings'].forEach(function(t){ $('tab-'+t).hidden = (t !== name); });
  if (name==='read') loadLibrary().catch(function(){});
  if (name==='wiki') loadWiki();
}
async function refreshHealth(){
  try { HEALTH = await (await fetch('/api/health')).json(); }
  catch(e){ HEALTH = null; }
  updateStatus();
  if (HEALTH && HEALTH.ok){
    $('api-key').value = '';
    $('base-url').value = HEALTH.base_url || 'https://api.deepseek.com';
    $('model').value = HEALTH.model || 'deepseek-chat';
    $('key-status').textContent = HEALTH.has_key
      ? '已保存 API Key。留空会沿用现有 Key。'
      : '尚未保存 API Key。';
  }
}

/* ---------- 问答 ---------- */
var SUGGEST = ['白玉蛊是怎么炼成的','十大尊者都有谁','方源为什么能重生','监天塔是什么','幽魂魔尊是什么人','春秋蝉有什么用'];
var CHARS = ['方源','白凝冰','古月方正','凤九歌','武庸','龙公','星宿仙尊','巨阳仙尊','幽魂魔尊','狂蛮魔尊','盗天魔尊','乐土仙尊'];
function renderSuggest(){
  var box = $('suggest');
  if (box) box.innerHTML = '';
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
function renderWikiCites(cites){
  if (!cites || !cites.length) return '';
  var html = '<div class="wiki-cites"><span class="wiki-cites-label">相关词条</span>';
  cites.forEach(function(c){
    html += '<button type="button" class="wiki-cite-chip" onclick="openWikiByName(\''+attrEsc(c.name)+'\')">'+esc(c.name)+'</button>';
  });
  html += '</div>';
  return html;
}
function renderSources(sources){
  if (!sources || !sources.length) return '';
  var html = '';
  sources.forEach(function(s){
    html += '<div class="src-card">' +
      '<div class="src-head"><span class="src-label">'+esc(s.label)+'</span>' +
      (s.type==='lore'
        ? '<button class="src-btn" data-act="lore-read" data-sec="'+attrEsc(s.title||s.section||'')+'">阅读原文</button>'
        : '<button class="src-btn" data-act="read" data-vol="'+attrEsc(s.vol)+'" data-ch="'+s.chapter+'">阅读原文</button>') +
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
    d.innerHTML = body + renderWikiCites(j.wiki_cites) + renderSources(shown) + cost;
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
  if (rt === 'pdf' || rt === 'rz'){
    loadLibrary().then(function(){
      var pane = $('read-'+rt);
      var chapters = rt === 'pdf' ? PDF_CHS : RZ_CHS;
      if (chapters.length && !pane.dataset.chapterLoaded){
        pane.dataset.chapterLoaded = '1';
        renderChapter(0, rt, pane);
      }
    }).catch(function(){});
  }
  if (rt === 'lore') loadLore();
}
function gotoNovelChapter(vol, ch){
  var libraryReady = !!LIB;
  PENDING_CHAPTER = {vol: vol, ch: Number(ch)};
  switchTab('read');
  switchReadTab('novel');
  if (libraryReady) showChapter(vol, Number(ch));
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
function loadLibrary(){
  if (LIB) return Promise.resolve(LIB);
  if (LIB_LOADING) return LIB_LOADING;
  var hadExplicitTarget = !!PENDING_CHAPTER;
  LIB_LOADING = fetch('/api/library').then(function(response){
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }).then(function(j){
    var volumes = Array.isArray(j.volumes) ? j.volumes : [];
    LIB = Object.assign({}, j, {volumes: volumes, pdfs: Array.isArray(j.pdfs) ? j.pdfs : []});
    var toc = $('read-novel').querySelector('.toc-body');
    toc.innerHTML = '';
    volumes.forEach(function(v){
      var chapters = Array.isArray(v.chapters) ? v.chapters : [];
      var det = document.createElement('details');
      det.className = 'toc-node lv1';
      var sum = document.createElement('summary');
      var s = document.createElement('span');
      s.className = 'toc-link';
      s.textContent = v.name;
      sum.appendChild(s);
      det.appendChild(sum);
      var list = document.createElement('div');
      list.className = 'toc-children';
      for (var gi = 0; gi < chapters.length; gi += 20){
        var chunk = chapters.slice(gi, gi + 20);
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
    if (!volumes.length) toc.innerHTML = '<div class="empty">未找到小说章节</div>';
    renderPdfLists(LIB.pdfs);

    var target = PENDING_CHAPTER;
    if (target) showChapter(target.vol, target.ch);
    else if (!hadExplicitTarget && !CUR_VOL){
      var firstVolume = volumes.find(function(v){ return Array.isArray(v.chapters) && v.chapters.length; });
      if (firstVolume) showChapter(firstVolume.name, firstVolume.chapters[0].n);
    }
    return LIB;
  }).catch(function(e){
    LIB = null;
    toast('阅读库加载失败：'+e.message);
    throw e;
  }).finally(function(){
    LIB_LOADING = null;
  });
  return LIB_LOADING;
}
async function showChapter(vol, ch){
  var requestId = ++CHAPTER_REQUEST_ID;
  try {
    var response = await fetch('/api/chapter?vol='+encodeURIComponent(vol)+'&chapter='+ch);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    var j = await response.json();
    if (requestId !== CHAPTER_REQUEST_ID) return;
    CUR_VOL = vol; CUR_CH = Number(ch);
    if (PENDING_CHAPTER && PENDING_CHAPTER.vol === vol && PENDING_CHAPTER.ch === Number(ch)) PENDING_CHAPTER = null;
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
    document.querySelectorAll('#read-novel .toc-leaf .toc-link').forEach(function(link){
      link.classList.remove('cur');
      if (link.getAttribute('data-vol') === vol && Number(link.getAttribute('data-ch')) === Number(ch)){
        link.classList.add('cur');
        var group = link.closest('.toc-node');
        if (group) group.open = true;
        var volume = group ? group.parentElement.closest('.toc-node.lv1') : null;
        if (volume) volume.open = true;
      }
    });
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
  pdfs = Array.isArray(pdfs) ? pdfs : [];
  PDF_CHS = [];
  var combined = pdfs.find(function(p){ return p.name.indexOf('1.1') >= 0; }) ||
                 pdfs.find(function(p){ return p.group === '插图版'; });
  var pane = $('read-pdf');
  pane.innerHTML = '<div class="toc-pane" id="pdf-toc-pane">' +
    '<div class="toc-head"><span class="toc-title">目录</span><button class="toc-fold" onclick="togglePdfToc()">«</button></div>' +
    '<div class="toc-body" id="pdf-toc-body"></div></div>' +
    '<div class="text-pane"><div class="pdf-view"><div class="empty">选择左侧章节查看</div></div></div>';
  $('pdf-toc-body').innerHTML = combined ? renderPdfList(combined, PDF_CHS, 'pdf') : '<div class="empty">未找到 PDF</div>';
  RZ_CHS = [];
  var rz = $('read-rz');
  var rzPdf = pdfs.find(function(p){ return p.group === '人祖传'; });
  if (rzPdf){
    rz.innerHTML = '<div class="toc-pane" id="rz-toc-pane">' +
      '<div class="toc-head"><span class="toc-title">目录</span><button class="toc-fold" onclick="toggleRzToc()">«</button></div>' +
      '<div class="toc-body" id="rz-toc-body"></div></div>' +
      '<div class="text-pane"><div class="pdf-view"><div class="empty">选择左侧章节查看</div></div></div>';
    $('rz-toc-body').innerHTML = renderPdfList(rzPdf, RZ_CHS, 'rz');
  } else {
    rz.innerHTML = '<div class="empty">未找到人祖传 PDF</div>';
  }
  delete pane.dataset.chapterLoaded;
  delete rz.dataset.chapterLoaded;
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
  var baseUrl = $('base-url').value.trim();
  var model = $('model').value.trim();
  var result = $('key-result');
  if (!baseUrl){ toast('请填写 Base URL'); return; }
  if (!model){ toast('请填写模型名'); return; }
  var settings = {base_url: baseUrl, model: model};
  if (key && key.indexOf('sk-已配置')!==0) settings.api_key = key;
  result.className='result'; result.textContent='正在测试连接…';
  try {
    var testResponse = await fetch('/api/settings/test', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(settings)
    });
    var t = await testResponse.json();
    if (!testResponse.ok || !t.ok) throw new Error(t.error||t.message||('HTTP '+testResponse.status));

    var saveResponse = await fetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(settings)
    });
    var saved = await saveResponse.json();
    if (!saveResponse.ok || !saved.ok) throw new Error(saved.error||('HTTP '+saveResponse.status));

    result.className='result ok';
    result.textContent = '连接成功并已保存：' + (t.models||[model]).join('、');
    await refreshHealth();
  } catch(e){ result.className='result err'; result.textContent='请求出错：'+e.message; }
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
      res.className='result ok'; res.textContent='已切换为：' + j.data_dir + '（'+ j.embed_model +'）';
      toast('检索模型已切换');
      refreshHealth();
    } else { res.className='result err'; res.textContent='切换失败：' + (j.error||'未知错误'); }
  } catch(e){ res.className='result err'; res.textContent='请求出错：'+e.message; }
}

/* ---------- 百科 ---------- */
var WIKI = null, WIKI_CAT = '人物', WIKI_SUB = '', WIKI_SUBS = {};
var WIKI_CURRENT = null, WIKI_VISIBLE = [];
async function loadWiki(){
  if (WIKI) return;
  try {
    var response = await fetch('/api/wiki');
    if (!response.ok) throw new Error('百科数据加载失败');
    WIKI = await response.json();
    // 统计蛊虫子分类分布
    WIKI_SUBS = {};
    (WIKI.categories['蛊虫'] || []).forEach(function(e){ WIKI_SUBS[e.sub || '其他'] = (WIKI_SUBS[e.sub || '其他'] || 0) + 1; });
    renderWikiCats();
  } catch(e){
    $('wiki-detail').innerHTML = '<div class="empty">百科数据暂时无法加载</div>';
  }
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
      b.classList.add('active'); WIKI_CAT = c; WIKI_SUB = ''; renderWikiSubs(); renderWikiList(c, true);
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
  renderWikiList(WIKI_CAT, true);
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
      s.classList.add('active'); WIKI_SUB = val; renderWikiList(WIKI_CAT, true);
    };
    sb.appendChild(s);
  };
  add('全部', '');
  order.forEach(function(o){ if (WIKI_SUBS[o]) add(o + '（' + WIKI_SUBS[o] + '）', o); });
}
function wikiEntryKey(e, cat){
  return (cat || e.section || '') + '\u0000' + (e.name || '');
}
function wikiExcerpt(text, length){
  var clean = String(text || '').replace(/\s+/g, ' ').trim();
  return clean.length > length ? clean.slice(0, length) + '…' : clean;
}
function renderWikiList(cat, selectFirst){
  var q = ($('wiki-search').value || '').trim();
  var box = $('wiki-list'); box.innerHTML = '';
  var visible = [];
  if (q){
    var found = [];
    Object.keys(WIKI.categories).forEach(function(c){
      (WIKI.categories[c] || []).forEach(function(e){
        if (e.name.indexOf(q) >= 0 || (e.desc || '').indexOf(q) >= 0) found.push({entry: e, cat: c});
      });
    });
    found.sort(function(a, b){ return (a.entry.name === q ? -1 : 0) - (b.entry.name === q ? -1 : 0); });
    visible = found.slice(0, 300);
  } else {
    visible = (WIKI.categories[cat] || [])
      .filter(function(e){ return !WIKI_SUB || (e.sub || '其他') === WIKI_SUB; })
      .slice(0, 800)
      .map(function(e){ return {entry: e, cat: cat}; });
  }
  WIKI_VISIBLE = visible;
  $('wiki-result-count').textContent = q
    ? '搜索到 ' + visible.length + ' 条' + (visible.length === 300 ? '（仅显示前 300 条）' : '')
    : (WIKI_SUB || cat) + ' · ' + visible.length + ' 条';
  visible.forEach(function(item, index){
    var e = item.entry;
    var d = document.createElement('button');
    d.type = 'button';
    d.className = 'wiki-item';
    d.dataset.wikiKey = wikiEntryKey(e, item.cat);
    d.innerHTML = '<span class="wiki-item-name">'+esc(e.name)+'</span>' +
      (q ? '<span class="wiki-badge">'+esc(item.cat)+'</span>' : '') +
      '<span class="wiki-item-desc">'+esc(wikiExcerpt(e.desc, 48))+'</span>';
    d.onclick = function(){ renderWikiDetail(e, item.cat, index); };
    box.appendChild(d);
  });
  if (!visible.length){
    box.innerHTML = '<div class="empty">没有匹配条目</div>';
    if (selectFirst) $('wiki-detail').innerHTML = '<div class="empty">尝试其他分类或搜索词</div>';
    return;
  }
  var currentIndex = visible.findIndex(function(item){
    return WIKI_CURRENT && wikiEntryKey(item.entry, item.cat) === WIKI_CURRENT.key;
  });
  if (selectFirst || currentIndex < 0) renderWikiDetail(visible[0].entry, visible[0].cat, 0);
  else setWikiActiveItem(WIKI_CURRENT.key);
}
function setWikiActiveItem(key){
  document.querySelectorAll('.wiki-item').forEach(function(item){
    var active = item.dataset.wikiKey === key;
    item.classList.toggle('active', active);
    if (active) item.setAttribute('aria-current', 'true');
    else item.removeAttribute('aria-current');
  });
}
function wikiParagraphs(text){
  var blocks = String(text || '').replace(/\r/g, '').split(/\n\s*\n|\n/)
    .map(function(p){ return p.trim(); }).filter(Boolean);
  if (blocks.length !== 1 || blocks[0].length < 260) return blocks;
  var sentences = blocks[0].match(/[^。！？!?；;]+[。！？!?；;]?/g) || blocks;
  var result = [], current = '';
  sentences.forEach(function(sentence){
    if (current && current.length + sentence.length > 210){ result.push(current); current = ''; }
    current += sentence;
  });
  if (current) result.push(current);
  return result;
}
function renderWikiDetail(e, cat, index){
  cat = cat || WIKI_CAT;
  if (typeof index !== 'number') index = WIKI_VISIBLE.findIndex(function(item){ return item.entry === e; });
  var key = wikiEntryKey(e, cat);
  WIKI_CURRENT = {key: key, entry: e, cat: cat};
  setWikiActiveItem(key);
  var paragraphs = wikiParagraphs(e.desc);
  var lead = paragraphs.shift() || '暂无条目摘要。';
  var body = paragraphs.map(function(p){ return '<p>'+esc(p)+'</p>'; }).join('');
  var prev = index > 0 ? WIKI_VISIBLE[index - 1] : null;
  var next = index >= 0 && index < WIKI_VISIBLE.length - 1 ? WIKI_VISIBLE[index + 1] : null;
  var sub = e.sub && e.sub !== '其他' ? '<div><dt>细分</dt><dd>'+esc(e.sub)+'</dd></div>' : '';
  $('wiki-detail').innerHTML =
    '<header class="wiki-article-head">' +
      '<div class="wiki-eyebrow">'+esc(cat)+'条目</div>' +
      '<h1 class="wiki-detail-name">'+esc(e.name)+'</h1>' +
      '<div class="wiki-byline">来自蛊箓百科</div>' +
    '</header>' +
    '<div class="wiki-article-grid">' +
      '<div class="wiki-article-copy">' +
        '<p class="wiki-lead">'+esc(lead)+'</p>' +
        (body ? '<section class="wiki-section"><h2>概述</h2>'+body+'</section>' : '') +
        '<section class="wiki-section wiki-source"><h2>资料来源</h2><p>本条目整理自「'+esc(e.section || cat)+'」资料库。</p></section>' +
      '</div>' +
      '<aside class="wiki-infobox" aria-label="条目信息">' +
        '<div class="wiki-infobox-title">条目信息</div>' +
        '<dl><div><dt>名称</dt><dd>'+esc(e.name)+'</dd></div><div><dt>分类</dt><dd>'+esc(cat)+'</dd></div>'+sub+'<div><dt>来源</dt><dd>'+esc(e.section || cat)+'</dd></div></dl>' +
        '<button class="btn btn-ghost wiki-ask" id="wiki-ask-btn">向 AI 询问此条目</button>' +
      '</aside>' +
    '</div>' +
    '<nav class="wiki-neighbors" aria-label="相邻条目">' +
      (prev ? '<button type="button" data-wiki-nav="prev"><span>上一篇</span>'+esc(prev.entry.name)+'</button>' : '<span></span>') +
      (next ? '<button type="button" data-wiki-nav="next"><span>下一篇</span>'+esc(next.entry.name)+'</button>' : '<span></span>') +
    '</nav>';
  document.getElementById('wiki-ask-btn').onclick = function(){ askAbout(e.name); };
  var prevButton = document.querySelector('[data-wiki-nav="prev"]');
  var nextButton = document.querySelector('[data-wiki-nav="next"]');
  if (prevButton) prevButton.onclick = function(){ renderWikiDetail(prev.entry, prev.cat, index - 1); };
  if (nextButton) nextButton.onclick = function(){ renderWikiDetail(next.entry, next.cat, index + 1); };
  $('wiki-detail').scrollTop = 0;
}
function askAbout(name){
  switchTab('chat');
  $('q').value = '介绍一下' + name;
  ask();
}
$('wiki-search').addEventListener('input', function(){ renderWikiList(WIKI_CAT, true); });

/* ---------- 游戏：选择题 ---------- */
var QUIZ_QS = [], QUIZ_IDX = 0, QUIZ_RIGHT = 0, QUIZ_N = 10, QUIZ_SEL = -1;
var QUIZ_T0 = 0, QUIZ_TIMER = null;
function quizScore(){ return {t: +(localStorage.getItem('gzr.quizTotal')||0), c: +(localStorage.getItem('gzr.quizCorrect')||0)}; }
function updateQuizScore(){
  var s = quizScore();
  $('quiz-score').textContent = '累计 ' + s.c + '/' + s.t;
}
function quizHistory(){ try { return JSON.parse(localStorage.getItem('gzr.quizHistory') || '[]'); } catch(e){ return []; } }
function fmtTime(sec){ sec = Math.max(0, Math.floor(sec)); var m = Math.floor(sec/60), s = sec%60; return (m<10?'0':'')+m+':'+(s<10?'0':'')+s; }
function startQuizTimer(){
  stopQuizTimer();
  QUIZ_T0 = Date.now();
  $('quiz-timer').textContent = '00:00';
  QUIZ_TIMER = setInterval(function(){
    $('quiz-timer').textContent = fmtTime((Date.now() - QUIZ_T0) / 1000);
  }, 250);
}
function stopQuizTimer(){ if (QUIZ_TIMER){ clearInterval(QUIZ_TIMER); QUIZ_TIMER = null; } }
function customQuiz(){ try { return JSON.parse(localStorage.getItem('gzr.customQuiz') || '[]'); } catch(e){ return []; } }
function saveCustomQuiz(list){ try { localStorage.setItem('gzr.customQuiz', JSON.stringify(list)); } catch(e){} }
function shuffleArray(a){ for (var i = a.length - 1; i > 0; i--){ var k = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[k]; a[k] = t; } return a; }
async function startQuiz(){
  var type = $('quiz-type').value;
  QUIZ_N = parseInt($('quiz-n').value, 10) || 10;
  $('quiz-body').innerHTML = '<div class="empty">出题中…</div>';
  try {
    var j = await (await fetch('/api/quiz', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({type: type, n: QUIZ_N})})).json();
    var qs = (j.questions || []).slice();
    var custom = customQuiz();
    if (custom.length){
      var extra = custom.filter(function(c){ return c.kind !== 'riddle' && (type === 'mix' || c.type === type || c.type === 'mix'); });
      qs = qs.concat(extra);
    }
    qs = shuffleArray(qs).slice(0, QUIZ_N);
    if (!qs.length) throw new Error('题库为空');
    QUIZ_QS = qs; QUIZ_IDX = 0; QUIZ_RIGHT = 0;
    startQuizTimer();
    renderQuizQ();
  } catch(e){ $('quiz-body').innerHTML = '<div class="empty">出题失败：'+esc(e.message)+'</div>'; }
}
function openQuizBank(){
  var list = customQuiz();
  $('cq-count').textContent = list.length;
  renderCustomQuizList();
  $('custom-quiz-modal').classList.add('show');
}
function renderCustomQuizList(){
  var box = $('cq-list'); if (!box) return;
  var list = customQuiz();
  if (!list.length){ box.innerHTML = '<div class="cq-empty">还没有自定义题目，用上面的表单添加，开始答题时会混入题库。</div>'; return; }
  var labels = {gu:'蛊虫', person:'人物', type:'蛊虫类型'};
  var rlabels = {gu:'蛊虫', person:'人物', item:'物品'};
  box.innerHTML = list.map(function(c, i){
    if (c.kind === 'riddle'){
      return '<div class="cq-item"><div class="cq-item-head"><b>[猜谜·'+esc(rlabels[c.type]||c.type)+'] 谜底：'+esc(c.name)+'</b><button class="cq-del" onclick="deleteCustomQuestion('+i+')">删除</button></div><div class="cq-item-opts">'+c.hints.map(function(h){ return '<span>'+esc(h)+'</span>'; }).join('')+'</div></div>';
    }
    return '<div class="cq-item"><div class="cq-item-head"><b>['+esc(labels[c.type]||c.type)+'] '+esc(c.q)+'</b><button class="cq-del" onclick="deleteCustomQuestion('+i+')">删除</button></div><div class="cq-item-opts">'+c.options.map(function(o, j){ return '<span'+(j === c.answer ? ' class="cq-right"' : '')+'>'+esc(o)+'</span>'; }).join('')+'</div></div>';
  }).join('');
}
function deleteCustomQuestion(i){
  var list = customQuiz(); list.splice(i, 1); saveCustomQuiz(list);
  var box = $('cq-count'); if (box) box.textContent = list.length;
  renderCustomQuizList(); toast('已删除该题目');
}
var CQ_KIND = 'quiz';
function switchCqKind(k){
  CQ_KIND = k;
  document.querySelectorAll('.cq-kind').forEach(function(b){ b.classList.toggle('active', b.dataset.kind === k); });
  $('cq-quiz-fields').hidden = k !== 'quiz';
  $('cq-riddle-fields').hidden = k !== 'riddle';
}
var DEFAULT_QUIZ_ALL = null;
async function ensureDefaultQuizAll(){
  if (DEFAULT_QUIZ_ALL) return DEFAULT_QUIZ_ALL;
  try { DEFAULT_QUIZ_ALL = await (await fetch('/api/quiz/all')).json(); }
  catch(e){ DEFAULT_QUIZ_ALL = {questions: [], riddle_names: {}}; }
  return DEFAULT_QUIZ_ALL;
}
function isDefaultDupQuiz(q){ return DEFAULT_QUIZ_ALL && DEFAULT_QUIZ_ALL.questions.indexOf(q) >= 0; }
function isDefaultDupRiddle(type, name){
  if (!DEFAULT_QUIZ_ALL || !DEFAULT_QUIZ_ALL.riddle_names) return false;
  var arr = DEFAULT_QUIZ_ALL.riddle_names[type] || [];
  return arr.indexOf(name) >= 0;
}
function addCustomQuestion(){
  var kind = CQ_KIND;
  var list = customQuiz();
  if (kind === 'riddle'){
    var name = ($('cq-rname').value || '').trim();
    var rtype = $('cq-rtype').value;
    var hints = ($('cq-rhints').value || '').split(/\n+/).map(function(s){ return s.trim(); }).filter(Boolean);
    if (!name){ toast('请填写谜底名称'); return; }
    if (hints.length < 5){ toast('提示不足 5 条（当前 '+hints.length+' 条），已剔除：请补足 5~10 条'); return; }
    var dup = list.some(function(c){ return c.kind === 'riddle' && c.type === rtype && c.name === name; });
    if (dup){ toast('题库中已有相同谜底，未添加'); return; }
    ensureDefaultQuizAll().then(function(){
      if (isDefaultDupRiddle(rtype, name)){ toast('该谜底与默认题库重复，未添加'); return; }
      list.push({kind: 'riddle', type: rtype, name: name, hints: hints.slice(0, 10)});
      saveCustomQuiz(list);
      $('cq-rname').value = ''; $('cq-rhints').value = '';
      $('cq-count').textContent = list.length;
      renderCustomQuizList(); toast('已添加猜谜题，玩猜谜时会混入');
    });
    return;
  }
  var type = $('cq-type').value;
  var q = ($('cq-q').value || '').trim();
  var opts = [0,1,2,3].map(function(i){ return ($('cq-o'+i).value || '').trim(); });
  var ans = parseInt($('cq-ans').value, 10);
  var exp = ($('cq-exp').value || '').trim();
  if (!q || opts.some(function(o){ return !o; })){ toast('请填写题目和四个选项'); return; }
  if (opts.some(function(o, i){ return opts.indexOf(o) !== i; })){ toast('四个选项不能重复'); return; }
  var dup = list.some(function(c){ return c.kind !== 'riddle' && c.q === q; });
  if (dup){ toast('题库中已有相同题目，未添加'); return; }
  ensureDefaultQuizAll().then(function(){
    if (isDefaultDupQuiz(q)){ toast('该题目与默认题库重复，未添加'); return; }
    list.push({kind: 'quiz', type: type, q: q, options: opts, answer: ans, explain: exp || '自定义题目'});
    saveCustomQuiz(list);
    $('cq-q').value = ''; [0,1,2,3].forEach(function(i){ $('cq-o'+i).value = ''; }); $('cq-exp').value = '';
    $('cq-count').textContent = list.length;
    renderCustomQuizList(); toast('已添加，开始答题时会混入题库');
  });
}
function importCustomQuiz(){
  var raw = ($('cq-import').value || '').trim();
  if (!raw){ toast('请粘贴 JSON 内容'); return; }
  var arr;
  try { arr = JSON.parse(raw); } catch(e){ toast('JSON 解析失败：'+e.message); return; }
  if (!Array.isArray(arr) || !arr.length){ toast('需要是一个 JSON 数组'); return; }
  var okQuiz = {gu:1, person:1, type:1}, okRiddle = {gu:1, person:1, item:1};
  var added = 0, skippedBad = 0, skippedDup = 0, skippedDefault = 0, skippedShort = 0;
  var list = customQuiz();
  var seen = {};
  list.forEach(function(it){
    if (it.kind === 'riddle') seen['r:' + it.type + ':' + it.name] = 1;
    else seen['q:' + it.q] = 1;
  });
  var batch = [];
  arr.forEach(function(item){
    if (!item || typeof item !== 'object'){ skippedBad++; return; }
    if (item.kind === 'riddle'){
      if (!item.name || !Array.isArray(item.hints) || !okRiddle[item.type]){ skippedBad++; return; }
      if (item.hints.length < 5){ skippedShort++; return; }
      batch.push({kind:'riddle', type:item.type, name:String(item.name).trim(), hints:item.hints.map(String).map(function(h){ return h.trim(); })});
      return;
    }
    if (!item.q || !Array.isArray(item.options) || item.options.length !== 4 || typeof item.answer !== 'number' || item.answer < 0 || item.answer >= 4 || !okQuiz[item.type]){ skippedBad++; return; }
    batch.push({kind:'quiz', type:item.type, q:String(item.q).trim(), options:item.options.map(String).map(function(o){ return o.trim(); }), answer:item.answer, explain:String(item.explain || 'AI 导入题目')});
  });
  // 批内去重 + 与自定义题库去重
  var batchSeen = {};
  var unique = [];
  batch.forEach(function(it){
    var key = it.kind === 'riddle' ? 'r:' + it.type + ':' + it.name : 'q:' + it.q;
    if (seen[key] || batchSeen[key]){ skippedDup++; return; }
    batchSeen[key] = 1;
    unique.push(it);
  });
  // 异步与默认题库去重后入库
  ensureDefaultQuizAll().then(function(d){
    var final = [];
    unique.forEach(function(it){
      if (it.kind === 'riddle'){
        if (isDefaultDupRiddle(it.type, it.name)){ skippedDefault++; return; }
      } else {
        if (isDefaultDupQuiz(it.q)){ skippedDefault++; return; }
      }
      final.push(it);
      added++;
    });
    list = list.concat(final);
    saveCustomQuiz(list);
    $('cq-count').textContent = list.length;
    $('cq-import').value = '';
    renderCustomQuizList();
    var msg = '导入成功 ' + added + ' 条';
    if (skippedDup) msg += '，剔除重复 ' + skippedDup + ' 条';
    if (skippedDefault) msg += '，与默认题库重复剔除 ' + skippedDefault + ' 条';
    if (skippedShort) msg += '，提示不足5条剔除 ' + skippedShort + ' 条';
    if (skippedBad) msg += '，剔除格式不符 ' + skippedBad + ' 条';
    toast(msg);
  });
}
function renderQuizQ(){
  if (QUIZ_IDX >= QUIZ_QS.length){ finishQuiz(); return; }
  var q = QUIZ_QS[QUIZ_IDX];
  var html = '<div class="quiz-q">第 '+(QUIZ_IDX+1)+' / '+QUIZ_QS.length+' 题 · '+esc(q.q)+'</div>';
  q.options.forEach(function(opt, i){
    html += '<button class="quiz-opt" onclick="selectQuizOption('+i+')">' + esc(opt) + '</button>';
  });
  html += '<button id="quiz-confirm" class="btn btn-primary" onclick="confirmQuiz()" disabled>确认答案</button>';
  html += '<div id="quiz-fb" class="quiz-fb"></div>';
  $('quiz-body').innerHTML = html;
}
function selectQuizOption(i){
  if (QUIZ_QS[QUIZ_IDX]._locked) return;
  QUIZ_SEL = i;
  document.querySelectorAll('.quiz-opt').forEach(function(b, idx){ b.classList.toggle('selected', idx === i); });
  $('quiz-confirm').disabled = false;
}
function confirmQuiz(){
  var q = QUIZ_QS[QUIZ_IDX];
  var right = (QUIZ_SEL === q.answer);
  q._locked = true;
  if (right) QUIZ_RIGHT++;
  var s = quizScore();
  s.t++; if (right) s.c++;
  localStorage.setItem('gzr.quizTotal', s.t); localStorage.setItem('gzr.quizCorrect', s.c);
  updateQuizScore();
  var fb = $('quiz-fb');
  fb.innerHTML = (right ? '答对了！' : '答错了，正确答案：<b>'+esc(q.options[q.answer])+'</b>') +
    '<br><span class="quiz-exp">'+esc(q.explain)+'</span>';
  var btn = $('quiz-confirm');
  btn.textContent = (QUIZ_IDX < QUIZ_QS.length-1 ? '下一题 →' : '查看成绩');
  btn.onclick = function(){ renderQuizQ(); };
  document.querySelectorAll('.quiz-opt').forEach(function(b, idx){
    b.disabled = true;
    if (idx === q.answer) b.classList.add('correct');
  });
  QUIZ_IDX++;
}
function finishQuiz(){
  stopQuizTimer();
  var sec = Math.round((Date.now() - QUIZ_T0) / 1000);
  var h = quizHistory();
  h.unshift({
    d: new Date().toLocaleString('zh-CN', {hour12:false}),
    type: $('quiz-type').value,
    n: QUIZ_QS.length,
    right: QUIZ_RIGHT,
    sec: sec
  });
  if (h.length > 30) h.length = 30;
  try { localStorage.setItem('gzr.quizHistory', JSON.stringify(h)); } catch(e){}
  renderQuizHistory();
  $('quiz-body').innerHTML = '<div class="empty">本组完成：答对 <b>'+QUIZ_RIGHT+'/'+QUIZ_QS.length+'</b>　用时 '+fmtTime(sec)+'<br><br><button class="btn btn-primary" onclick="startQuiz()">再来一组</button></div>';
}
function renderQuizHistory(){
  var box = $('quiz-history-list'); if (!box) return;
  var h = quizHistory();
  if (!h.length){ box.innerHTML = '<div class="quiz-history-empty">暂无记录，完成一组题目后自动保存。</div>'; return; }
  var labels = {mix:'混合', gu:'蛊虫', person:'人物', type:'蛊虫类型'};
  box.innerHTML = h.map(function(r){
    return '<div class="quiz-history-item"><span>'+esc(r.d)+'</span><span>'+esc(labels[r.type]||r.type)+' · '+r.n+' 题</span><b>'+r.right+' / '+r.n+'</b><span>'+fmtTime(r.sec)+'</span></div>';
  }).join('');
}
function clearQuizHistory(){
  localStorage.removeItem('gzr.quizHistory');
  renderQuizHistory();
}
function openGameHistory(){
  var body = $('game-history-body'); if (!body) return;
  var qh = quizHistory(), rh = riddleHistory();
  var labels = {mix:'混合', gu:'蛊虫', person:'人物', type:'蛊虫类型'};
  var rlabels = {gu:'蛊虫', person:'人物', item:'物品'};
  var h = '<div class="gh-sec"><h4>选择题记录</h4>';
  if (!qh.length) h += '<div class="gh-empty">暂无记录，完成一组选择题后自动保存。</div>';
  else h += qh.map(function(r){
    return '<div class="gh-row"><span>'+esc(r.d)+'</span><span>'+esc(labels[r.type]||r.type)+' · '+r.n+' 题</span><b>'+r.right+' / '+r.n+'</b><span>'+fmtTime(r.sec)+'</span></div>';
  }).join('');
  h += '</div><div class="gh-sec"><h4>猜谜记录</h4>';
  if (!rh.length) h += '<div class="gh-empty">暂无记录，猜完一道谜题后自动保存。</div>';
  else h += rh.map(function(r){
    return '<div class="gh-row"><span>'+esc(r.d)+'</span><span>猜'+esc(rlabels[r.type]||r.type)+' · '+esc(r.name)+'</span><b class="'+(r.result==='对'?'gh-ok':'gh-bad')+'">'+esc(r.result)+(r.pts?' (+'+r.pts+')':'')+'</b><span></span></div>';
  }).join('');
  h += '</div><div class="gh-clear"><button class="btn btn-ghost" onclick="clearGameHistory()">清空全部记录</button></div>';
  body.innerHTML = h;
  $('game-history-modal').classList.add('show');
}
function clearGameHistory(){
  localStorage.removeItem('gzr.quizHistory');
  localStorage.removeItem('gzr.riddleHistory');
  toast('已清空游戏历史记录');
  openGameHistory();
}

/* ---------- 游戏：猜谜 ---------- */
var RIDDLE = null, RIDDLE_IDX = 0, RIDDLE_TYPE = 'gu', RIDDLE_LABEL = '猜蛊虫';
function riddleScore(){ return +(localStorage.getItem('gzr.riddleScore')||0); }
function updateRiddleScore(){ $('riddle-score').textContent = '累计 ' + riddleScore() + ' 分'; }
async function newRiddle(){
  $('riddle-body').innerHTML = '<div class="empty">出题中…</div>';
  try {
    var j = await (await fetch('/api/riddle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({type: RIDDLE_TYPE, n: 1})})).json();
    var pool = (j.riddles || []).slice();
    var custom = customQuiz().filter(function(c){ return c.kind === 'riddle' && c.type === RIDDLE_TYPE; });
    pool = pool.concat(custom);
    if (!pool.length) throw new Error('谜题池为空');
    RIDDLE = pool[Math.floor(Math.random() * pool.length)]; RIDDLE_IDX = 0;
    renderRiddle();
  } catch(e){ $('riddle-body').innerHTML = '<div class="empty">出题失败：'+esc(e.message)+'</div>'; }
}
function riddleHistory(){ try { return JSON.parse(localStorage.getItem('gzr.riddleHistory') || '[]'); } catch(e){ return []; } }
function recordRiddle(ok, pts){
  var h = riddleHistory();
  h.unshift({d: new Date().toLocaleString('zh-CN', {hour12:false}), type: RIDDLE_TYPE, name: RIDDLE.name, result: ok ? '对' : '错', pts: pts});
  if (h.length > 40) h.length = 40;
  try { localStorage.setItem('gzr.riddleHistory', JSON.stringify(h)); } catch(e){}
}
function renderRiddle(){
  var html = '<div class="riddle-hints">';
  for (var i=0; i<=RIDDLE_IDX; i++) html += '<div class="riddle-hint">提示'+(i+1)+'：'+esc(RIDDLE.hints[i])+'</div>';
  html += '</div>';
  if (RIDDLE_IDX < RIDDLE.hints.length - 1) html += '<br><button class="btn btn-ghost" onclick="moreHint()">更多提示（-1分）</button>';
  html += '<div class="riddle-ask"><input id="riddle-input" placeholder="输入你的答案…" autocomplete="off"><button class="btn btn-primary" onclick="guessRiddle()">猜！</button></div>';
  html += '<div id="riddle-fb"></div>';
  $('riddle-body').innerHTML = html;
  var inp = $('riddle-input'); if (inp) { inp.focus(); inp.addEventListener('keydown', function(e){ if (e.key==='Enter') guessRiddle(); }); }
}
function moreHint(){
  if (RIDDLE_IDX >= RIDDLE.hints.length - 1) return;
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
    var pts = Math.max(1, 8 - RIDDLE_IDX);
    localStorage.setItem('gzr.riddleScore', riddleScore() + pts);
    updateRiddleScore();
    recordRiddle(true, pts);
    fb.innerHTML = '猜对了！+'+pts+'分　答案：<b>'+esc(RIDDLE.name)+'</b><br><br><button class="btn btn-primary" onclick="newRiddle()">再来一道</button>';
  } else if (RIDDLE_IDX >= RIDDLE.hints.length - 1){
    recordRiddle(false, 0);
    fb.innerHTML = '没猜中，答案是：<b>'+esc(RIDDLE.name)+'</b><br><br><button class="btn btn-primary" onclick="newRiddle()">再来一道</button>';
  } else {
    fb.innerHTML = '不对，再想想（可用「更多提示」）';
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
      $('riddle-label').textContent = {'gu':'猜蛊虫','person':'猜人物','item':'猜物品'}[RIDDLE_TYPE] || gt;
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
    html += '<details class="nav-arch"><summary>已归档（' + archived.length + '）</summary>' +
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
