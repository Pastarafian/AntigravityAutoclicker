"""
VegaClick v16 — Deep Scanner + Fast Clicker Architecture
==========================================================
Two-part system:
 1. DEEP SCANNER — walks entire DOM tree, shadow roots, iframes, finds ALL clickable elements
 2. FAST CLICKER — reads scanner results, clicks matching buttons instantly

The scanner feeds window.__vcTargets to the clicker.
"""

import tkinter as tk
import json
import asyncio
import websockets
import urllib.request
import threading
import time
import queue
import os
import subprocess
import sys

PORT = 9222
POLL_INTERVAL = 0.8

command_queue = queue.Queue()

# ═══════════════════════════════════════════════════════════════
# Agentic Bridge — inject prompts into IDE chat
# ═══════════════════════════════════════════════════════════════

INJECT_JS = """
(function() {
    var text = %s;
    var box = document.querySelector('textarea, [contenteditable="true"]') || document.querySelector('input[type="text"]');
    if (!box) return "No input box found";
    if (box.tagName === 'TEXTAREA' || box.tagName === 'INPUT') {
        box.value = text;
        box.dispatchEvent(new Event('input', {bubbles: true}));
    } else {
        box.innerText = text;
        box.dispatchEvent(new Event('input', {bubbles: true}));
    }
    var btn = document.querySelector('button[type="submit"]') || (box.parentElement && box.parentElement.querySelector('button'));
    if (btn) btn.click();
    else box.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
    return "Injected prompt";
})()
"""

READ_DOM_JS = """(function(){ return document.body.innerText; })()"""

def start_agentic_bridge():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args): pass
        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(length).decode('utf-8')) if length > 0 else {}
                if self.path == '/api/inject':
                    command_queue.put({'action': 'inject', 'prompt': data.get('prompt', '')})
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"status": "queued"}')
                else:
                    self.send_response(404); self.end_headers()
            except:
                self.send_response(400); self.end_headers()
        def do_GET(self):
            if self.path == '/api/dom':
                res_q = queue.Queue()
                command_queue.put({'action': 'read_dom', 'res_q': res_q})
                try:
                    res = res_q.get(timeout=5)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"dom": res}).encode('utf-8'))
                except queue.Empty:
                    self.send_response(504); self.end_headers()
            elif self.path == '/api/status':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "ok", "version": "v16"}')
    try:
        HTTPServer(('127.0.0.1', 4242), Handler).serve_forever()
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# Process Cleanup
# ═══════════════════════════════════════════════════════════════
def cleanup_old_processes():
    my_pid = os.getpid()
    kill_patterns = ['ide-autoclicker', 'vegaclaw', 'vegaclick', 'autoclicker']
    try:
        result = subprocess.run(
            ['wmic', 'process', 'where', "name='pythonw.exe' or name='python.exe'",
             'get', 'ProcessId,CommandLine', '/format:list'],
            capture_output=True, text=True, timeout=5
        )
        current_pid = None; current_cmd = None
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('CommandLine='): current_cmd = line[12:].lower()
            elif line.startswith('ProcessId='):
                current_pid = int(line[10:])
                if current_pid != my_pid and current_cmd and any(p in current_cmd for p in kill_patterns):
                    try: subprocess.run(['taskkill', '/PID', str(current_pid), '/F'], capture_output=True, timeout=3)
                    except: pass
                current_pid = None; current_cmd = None
    except: pass

# ═══════════════════════════════════════════════════════════════
# VegaClick v16 — DEEP SCANNER + FAST CLICKER JS
# ═══════════════════════════════════════════════════════════════
FINDER_JS = r"""
(function(){
  // ─── HEARTBEAT ───
  if(window.__vc && (Date.now() - window.__vchb < 10000)) {
    var typLeft = window.__vctyping ? Math.max(0, 5000 - (Date.now() - window.__vctyping)) : 0;
    var scrLeft = window.__vcscrolling ? Math.max(0, 15000 - (Date.now() - window.__vcscrolling)) : 0;
    var cd = Math.max(typLeft, scrLeft);
    return JSON.stringify({s:'active', c:window.__vcc||0, m:window.__vcm||'', inv:window.__vcTargets?window.__vcTargets.length:0, ml:window.__vcMLStats||{}, cd:cd});
  }

  // ─── CLEANUP ───
  if(window.__vcObs) { try{window.__vcObs.disconnect();}catch(e){} }
  if(window.__vcInt) clearInterval(window.__vcInt);
  if(window.__vcScanInt) clearInterval(window.__vcScanInt);
  if(window.__vcKD) document.removeEventListener('keydown', window.__vcKD, true);
  if(window.__vcWH) document.removeEventListener('wheel', window.__vcWH, true);
  if(window.__vcTM) document.removeEventListener('touchmove', window.__vcTM, true);

  // ─── STATE ───
  window.__vc = true;
  window.__vchb = Date.now();
  window.__vcc = window.__vcc || 0;
  window.__vcm = window.__vcm || '';
  window.__vctyping = 0;
  window.__vcoverlay = true;
  window.__vcTargets = [];  // Scanner results — the clicker reads from here
  window.__vcClicked = {};  // Dedup map: hash -> timestamp

  // ═══════════════════════════════════════════════════════════
  // MACHINE LEARNING STATE
  // Learns from successful/failed clicks, persists in localStorage
  // ═══════════════════════════════════════════════════════════
  try {
    window.__vcML = JSON.parse(localStorage.getItem('__vcML') || '{}');
  } catch(e) { window.__vcML = {}; }
  // ML structure: { signature: { hits: N, misses: N, score: N, lastSeen: timestamp } }
  window.__vcMLStats = { learned: Object.keys(window.__vcML).length, rewarded: 0, punished: 0, blocked: 0 };

  // ─── ML: Extract element signature for learning ───
  function getSignature(el, kw) {
    var tag = el.tagName ? el.tagName.toLowerCase() : '?';
    var cls = (el.className||'').toString().split(/\s+/).slice(0,3).sort().join(',');
    var pTag = el.parentElement ? el.parentElement.tagName.toLowerCase() : '?';
    var pCls = el.parentElement ? (el.parentElement.className||'').toString().split(/\s+/).slice(0,2).sort().join(',') : '';
    return kw + '|' + tag + '|' + cls.slice(0,40) + '|' + pTag + '|' + pCls.slice(0,30);
  }

  // ─── ML: Record success (button disappeared after click) ───
  function mlReward(sig) {
    if(!window.__vcML[sig]) window.__vcML[sig] = {hits:0, misses:0, score:0, lastSeen:0};
    window.__vcML[sig].hits++;
    window.__vcML[sig].score = Math.min(window.__vcML[sig].score + 2, 20); // Cap at +20
    window.__vcML[sig].lastSeen = Date.now();
    window.__vcMLStats.rewarded++;
    try { localStorage.setItem('__vcML', JSON.stringify(window.__vcML)); } catch(e){}
  }

  // ─── ML: Record failure (button still visible after click) ───
  function mlPunish(sig) {
    if(!window.__vcML[sig]) window.__vcML[sig] = {hits:0, misses:0, score:0, lastSeen:0};
    window.__vcML[sig].misses++;
    window.__vcML[sig].score = Math.max(window.__vcML[sig].score - 1, -10); // Floor at -10
    window.__vcML[sig].lastSeen = Date.now();
    window.__vcMLStats.punished++;
    try { localStorage.setItem('__vcML', JSON.stringify(window.__vcML)); } catch(e){}
  }

  // ─── ML: Get priority adjustment for a signature ───
  function mlBoost(sig) {
    var data = window.__vcML[sig];
    if(!data) return 0;
    if(data.score <= -5) { window.__vcMLStats.blocked++; return -999; } // Auto-block bad patterns
    return data.score; // Positive = boost, negative = demote
  }

  // ─── TYPING DETECTION (5s cooldown) ───
  window.__vcKD = function(e){
    if(e.key && (e.key.length===1||e.key==='Backspace'||e.key==='Enter'||e.key==='Tab'))
      window.__vctyping = Date.now();
  };
  document.addEventListener('keydown', window.__vcKD, true);

  // ─── SCROLL DETECTION (15s cooldown for auto-scroll only) ───
  window.__vcscrolling = 0;
  window.__vcWH = function(){ window.__vcscrolling = Date.now(); };
  window.__vcTM = function(){ window.__vcscrolling = Date.now(); };
  document.addEventListener('wheel', window.__vcWH, true);
  document.addEventListener('touchmove', window.__vcTM, true);

  // ─── AUTO-SCROLL: Keep chat pinned to bottom ───
  function autoScroll() {
    // Don't auto-scroll if user scrolled in last 15s
    if(Date.now() - window.__vcscrolling < 15000) return;
    var containers = document.querySelectorAll('[class*="overflow"]');
    for(var i=0; i<containers.length; i++){
      var el = containers[i];
      var cs = window.getComputedStyle(el);
      if((cs.overflowY==='auto'||cs.overflowY==='scroll') && el.scrollHeight > el.clientHeight + 50){
        var distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
        if(distFromBottom > 200){
          el.scrollTop = el.scrollHeight;
        }
      }
    }
  }

  // ─── BLOCKLIST ───
  var BL = [
    'delete','remove','uninstall','format','reset','sign out','log out',
    'close','cancel','discard','reject','deny','dismiss','erase','drop',
    'run and debug','go back','go forward','more actions','always run',
    'running','runner','run extension','run_cli','rescue run','rescue',
    'allowlist','restart','reload','rules','mcp','feedback','star'
  ];

  // ─── DANGER COMMANDS ───
  var BCMD = ['rm ','rm -','del ','format ','fdisk','mkfs','dd if=','DROP TABLE','DROP DATABASE'];

  // ═══════════════════════════════════════════════════════════
  // PART 1: DEEP SCANNER
  // Walks ENTIRE DOM tree including shadow DOMs and iframes
  // Finds ALL elements, checks text against keywords
  // Stores matches in window.__vcTargets
  // ═══════════════════════════════════════════════════════════
  function deepScan() {
    var targets = [];
    var seen = new Set();

    function walk(root, depth) {
      if(depth > 12) return;
      try {
        // Get ALL elements in this root
        var all = root.querySelectorAll('*');
        for(var i = 0; i < all.length; i++) {
          var e = all[i];
          if(seen.has(e)) continue;
          seen.add(e);

          // Get text from multiple sources
          var raw = '';
          // For leaf-ish elements, use textContent; for containers, use first line of innerText
          var inner = (e.innerText || '').trim();
          var textC = (e.textContent || '').trim();
          var aria = (e.getAttribute('aria-label') || '').trim();
          var title = (e.getAttribute('title') || '').trim();
          var val = (e.getAttribute('value') || '').trim();

          // Prefer short text sources (more specific)
          if(inner && inner.length < 60) raw = inner;
          else if(textC && textC.length < 60) raw = textC;
          else if(aria) raw = aria;
          else if(title) raw = title;
          else if(val) raw = val;

          if(!raw) {
            // Enter shadow roots even if no text
            if(e.shadowRoot) walk(e.shadowRoot, depth+1);
            continue;
          }

          var t = raw.split(/\r?\n/)[0].trim().toLowerCase();
          if(t.length > 60 || t.length < 2) {
            if(e.shadowRoot) walk(e.shadowRoot, depth+1);
            continue;
          }

          // Blocklist check
          var blocked = false;
          for(var bi=0; bi<BL.length; bi++){
            if(t.indexOf(BL[bi])>=0){ blocked=true; break; }
          }

          // Skip menubar and non-chat UI elements
          var cls = (e.className||'').toString().toLowerCase();
          var tag = e.tagName ? e.tagName.toLowerCase() : '';

          // Skip list: editor, code, tabs, terminal, status bar, diff viewer, sidebar
          if(cls.indexOf('menubar-menu')>=0 || cls.indexOf('menu-item')>=0 ||
             cls.indexOf('mtk')>=0 ||           // Monaco token (code highlighting)
             cls.indexOf('monaco-icon-label')>=0 || // File path labels
             cls.indexOf('tab ')>=0 || cls.indexOf('tab-')>=0 || // File tabs
             cls.indexOf('diffeditor')>=0 || cls.indexOf('diff-')>=0 || // Diff view
             cls.indexOf('editor-container')>=0 ||  // Editor area
             cls.indexOf('xterm')>=0 ||          // Terminal
             cls.indexOf('statusbar')>=0 ||      // Status bar
             cls.indexOf('minimap')>=0 ||         // Minimap
             cls.indexOf('breadcrumb')>=0 ||      // Breadcrumbs
             cls.indexOf('explorer')>=0 ||        // File explorer
             cls.indexOf('label-name')>=0 ||      // Tab labels
             cls.indexOf('filename-link')>=0 ||   // Filename links in chat (not buttons)
             cls.indexOf('action-card')>=0 ||     // Sidebar action cards
             cls.indexOf('action-row')>=0 ||      // Sidebar action rows
             cls.indexOf('sidebar')>=0 ||         // Sidebar elements
             cls.indexOf('settings')>=0 ||        // Settings panels
             cls.indexOf('global-tooltip')>=0 ||  // Tooltips
             (tag === 'span' && cls.indexOf('mtk')>=0) || // Code spans
             (tag === 'div' && cls.indexOf('view-line')>=0)) { // Editor lines
            if(e.shadowRoot) walk(e.shadowRoot, depth+1);
            continue;
          }

          // Also skip if element is inside the editor (role=tab = file tab, not action button)
          if(tag !== 'button' && e.getAttribute('role') === 'tab') {
            if(e.shadowRoot) walk(e.shadowRoot, depth+1);
            continue;
          }

          // PARENT CHECK: skip if inside sidebar, action-card, settings panel
          var inSidebar = false;
          var pp = e.parentElement;
          for(var pi=0; pi<6 && pp; pi++){
            var pc = (pp.className||'').toString().toLowerCase();
            var pt = pp.tagName ? pp.tagName.toLowerCase() : '';
            if(pc.indexOf('sidebar')>=0 || pc.indexOf('action-card')>=0 ||
               pc.indexOf('action-row')>=0 || pc.indexOf('settings')>=0 ||
               pc.indexOf('panel-container')>=0 || pc.indexOf('pane-body')>=0 ||
               pt === 'sidebar-footer' || pt === 'sidebar-header'){
              inSidebar = true; break;
            }
            pp = pp.parentElement;
          }
          if(inSidebar) continue;

          if(blocked) {
            if(e.shadowRoot) walk(e.shadowRoot, depth+1);
            continue;
          }

          // ─── KEYWORD MATCHING ───
          var kw = null, priority = 0;

          if(t === 'accept all' || t.indexOf('accept all') === 0)
            { kw='accept all'; priority=100; }
          else if(t === 'accept' || t.indexOf('accept ') === 0)
            { kw='accept'; priority=90; }
          else if(t === 'allow in this conversation' || t === 'allow this conversation')
            { kw='allow'; priority=85; }
          else if(t === 'trust' || t.indexOf('trust ') === 0)
            { kw='trust'; priority=85; }
          else if(t === 'approve' || t.indexOf('approve ') === 0)
            { kw='approve'; priority=80; }
          else if(t === 'continue')
            { kw='continue'; priority=75; }
          else if(t.indexOf('run') === 0)
            { kw='run'; priority=70; }
          else if(t === 'retry')
            { kw='retry'; priority=65; }
          else if(t === 'ok')
            { kw='ok'; priority=60; }
          else if(t === 'yes')
            { kw='yes'; priority=55; }
          else if(t === 'apply')
            { kw='apply'; priority=50; }
          else if(t === 'relocate')
            { kw='relocate'; priority=45; }
          else if(t.indexOf('changes overview') === 0)
            { kw='changes overview'; priority=40; }

          if(kw) {
            targets.push({el:e, kw:kw, priority:priority, text:t, depth:depth});
          }

          // Always recurse into shadow roots
          if(e.shadowRoot) walk(e.shadowRoot, depth+1);
        }

        // Recurse into iframes
        var iframes = root.querySelectorAll('iframe, webview');
        for(var j=0; j<iframes.length; j++){
          try {
            var doc = iframes[j].contentDocument || (iframes[j].contentWindow && iframes[j].contentWindow.document);
            if(doc) walk(doc, depth+1);
          } catch(e){}
        }
      } catch(e){}
    }

    walk(document, 0);
    window.__vcTargets = targets;
  }

  // ═══════════════════════════════════════════════════════════
  // PART 2: FAST CLICKER
  // Reads from window.__vcTargets (populated by scanner)
  // Quickly filters for visibility, dedup, danger
  // Clicks all valid targets in priority order
  // ═══════════════════════════════════════════════════════════
  function clickTargets() {
    window.__vchb = Date.now();

    // Typing cooldown (5s)
    if(Date.now() - window.__vctyping < 5000) return;

    // Auto-scroll chat (respects 15s scroll cooldown)
    autoScroll();

    var targets = window.__vcTargets || [];
    if(targets.length === 0) return;

    var candidates = [];

    for(var i=0; i<targets.length; i++){
      var t = targets[i];
      var e = t.el;
      if(!e || !e.isConnected) continue; // Element removed from DOM
      if(e.dataset && e.dataset.vc16) continue; // Already clicked

      // Visibility check
      var r;
      try { r = e.getBoundingClientRect(); } catch(ex){ continue; }
      if(r.width === 0 || r.height === 0) continue;
      if(r.top < -10 || r.bottom > window.innerHeight + 50) continue;
      try {
        var cs = window.getComputedStyle(e);
        if(cs.display === 'none' || cs.visibility === 'hidden') continue;
      } catch(ex){}

      // Danger check for 'run'
      if(t.kw === 'run') {
        var danger = false, p = e;
        for(var j=0; j<4 && p; j++){
          try {
            var cd = p.querySelector('code,pre');
            if(cd){
              var cdt = (cd.textContent||'');
              for(var di=0; di<BCMD.length; di++){
                if(cdt.indexOf(BCMD[di])>=0){ danger=true; break; }
              }
            }
          } catch(ex){}
          if(danger) break;
          p = p.parentElement;
        }
        if(danger) continue;
      }

      // Dedup check
      var hash = t.kw + '|' + Math.round(r.left/20) + '|' + Math.round(r.top/20);
      var lastClick = window.__vcClicked[hash];
      if(lastClick && Date.now() - lastClick < 5000) continue;

      // ML: Adjust priority based on learned patterns
      var sig = getSignature(e, t.kw);
      var boost = mlBoost(sig);
      if(boost <= -999) continue; // ML blocked this pattern
      var adjPriority = t.priority + boost;

      candidates.push({el:e, kw:t.kw, priority:adjPriority, rect:r, hash:hash, text:t.text, sig:sig});
    }

    // Sort by priority
    candidates.sort(function(a,b){ return b.priority - a.priority; });

    // Inject ripple CSS
    if(candidates.length > 0 && window.__vcoverlay && !window.__vccss){
      window.__vccss = true;
      var st = document.createElement('style');
      st.textContent = '@keyframes vcripple{0%{transform:scale(0.5);opacity:1}100%{transform:scale(2.5);opacity:0}}';
      document.head.appendChild(st);
    }

    var colors = {
      'run':'59,130,246','accept all':'34,197,94','accept':'34,197,94',
      'allow':'34,197,94','trust':'34,197,94','continue':'34,197,94',
      'retry':'234,179,8','approve':'99,102,241','changes overview':'168,85,247'
    };

    // Click all
    for(var ci=0; ci<candidates.length; ci++){
      var c = candidates[ci];
      var el = c.el;
      var rect = c.rect;

      el.dataset.vc16 = '1';
      window.__vcClicked[c.hash] = Date.now();

      // Click dispatch
      try {
        var cx = rect.left + rect.width/2;
        var cy = rect.top + rect.height/2;
        el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true,clientX:cx,clientY:cy}));
        el.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,cancelable:true,clientX:cx,clientY:cy}));
        el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,clientX:cx,clientY:cy}));
        if(typeof el.click==='function') setTimeout(function(){try{el.click();}catch(e){}}, 50);
      } catch(ex){
        try{el.click();}catch(e2){}
      }

      if(typeof el.blur==='function') el.blur();

      // Visual ripple
      if(window.__vcoverlay){
        var rgb = colors[c.kw]||'139,92,246';
        var dx = Math.round(rect.left+rect.width/2);
        var dy = Math.round(rect.top+rect.height/2);
        var dot = document.createElement('div');
        dot.style.cssText = 'position:fixed;pointer-events:none;z-index:999999;border-radius:50%;'+
          'left:'+(dx-16)+'px;top:'+(dy-16)+'px;width:32px;height:32px;'+
          'border:3px solid rgba('+rgb+',0.9);background:rgba('+rgb+',0.3);'+
          'animation:vcripple 0.5s ease-out forwards;';
        document.body.appendChild(dot);
        setTimeout(function(){try{dot.remove();}catch(e){}}, 600);
      }

      window.__vcc++;
      window.__vcm = 'Clicked ' + c.kw + ' (' + c.text.slice(0,15) + ')';

      // ─── ML: Success/failure detection ───
      // After 600ms, check if the element disappeared (success) or stayed (failure)
      (function(el, sig, kw){
        var wasRect = {l: el.getBoundingClientRect().left, t: el.getBoundingClientRect().top};
        setTimeout(function(){
          try {
            // Check if element is still in DOM and visible
            if(!el.isConnected) {
              // Element removed from DOM = definite success
              mlReward(sig);
              return;
            }
            var newRect = el.getBoundingClientRect();
            if(newRect.width === 0 || newRect.height === 0) {
              // Element hidden = success
              mlReward(sig);
              return;
            }
            var cs = window.getComputedStyle(el);
            if(cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') {
              // Element hidden via CSS = success
              mlReward(sig);
              return;
            }
            // Element moved significantly = probably success (UI reshuffled)
            if(Math.abs(newRect.left - wasRect.l) > 50 || Math.abs(newRect.top - wasRect.t) > 50) {
              mlReward(sig);
              return;
            }
            // Element still there and unchanged = failure/misclick
            mlPunish(sig);
          } catch(ex) {
            // If we can't check, assume success (element might have been removed)
            mlReward(sig);
          }
            // Clear click flag
          try { delete el.dataset.vc16; } catch(e){}
        }, 600);
      })(el, c.sig, c.kw);

      // Clear flag after 5s as fallback
      (function(el){setTimeout(function(){try{delete el.dataset.vc16;}catch(e){}}, 5000);})(el);
    }

    // Cleanup old dedup entries
    var now = Date.now();
    for(var key in window.__vcClicked){
      if(now - window.__vcClicked[key] > 10000) delete window.__vcClicked[key];
    }
  }

  // ═══════════════════════════════════════════════════════════
  // PART 3: ORCHESTRATOR
  // Deep scan runs every 2s (thorough but heavier)
  // Click check runs every 100ms on mutation + every 500ms
  // ═══════════════════════════════════════════════════════════

  // Initial deep scan
  deepScan();

  // Deep scan on interval (re-walks entire DOM)
  window.__vcScanInt = setInterval(deepScan, 2000);

  // Fast clicker on mutation observer
  var thr = null;
  window.__vcObs = new MutationObserver(function(){
    // Re-scan on DOM changes (quick scan + click)
    deepScan();
    if(thr) return;
    thr = setTimeout(function(){ thr=null; clickTargets(); }, 80);
  });
  window.__vcObs.observe(document.body, {childList:true, subtree:true});

  // Fast clicker on interval
  window.__vcInt = setInterval(clickTargets, 500);
  setTimeout(clickTargets, 200);

  return JSON.stringify({s:'injected', c:0, m:'v16 deep scanner injected', cd:0});
})()
"""

# ═══════════════════════════════════════════════════════════════
# CDP Helpers
# ═══════════════════════════════════════════════════════════════

async def get_targets_async():
    all_targets = []
    async def probe(port):
        try:
            loop = asyncio.get_event_loop()
            data = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=0.3).read()),
                timeout=0.5)
            return json.loads(data)
        except: return []
    results = await asyncio.gather(*[probe(p) for p in range(9222, 9242)], return_exceptions=True)
    for r in results:
        if isinstance(r, list): all_targets.extend(r)
    return all_targets

async def _cdp_eval(ws_url, js_code):
    try:
        async with websockets.connect(ws_url, close_timeout=1) as ws:
            await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":js_code,"returnByValue":True}}))
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    except: return None

# ═══════════════════════════════════════════════════════════════
# UI Pill
# ═══════════════════════════════════════════════════════════════

class VegaClickApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("VegaClick v16")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.95)
        self.root.configure(bg='#0e1117')

        self.paused = False
        self.stopped = False
        self.total_clicks = 0
        self.cooldown = 0
        self.status_text = "Searching..."
        self.status_color = "#f59e0b"
        self.last_msg = ""
        self.pages_connected = 0
        self.scan_targets = 0

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"480x30+{sw - 500}+{sh - 70}")

        frame = tk.Frame(self.root, bg='#0e1117')
        frame.place(x=8, rely=0.5, anchor='w')

        tk.Label(frame, text="VegaClick", font=("Segoe UI", 9, "bold"), fg='#00d4ff', bg='#0e1117').pack(side='left', padx=(0,4))
        tk.Label(frame, text="16", font=("Consolas", 8, "bold"), fg='#a78bfa', bg='#1c2128').pack(side='left', padx=(0,8), ipady=1, ipadx=2)

        self.ui_status = tk.Label(frame, text="...", font=("Consolas", 9), fg=self.status_color, bg='#0e1117', width=16, anchor='w')
        self.ui_status.pack(side='left', padx=(0,8))

        self.ui_count = tk.Label(frame, text="0 clicks", font=("Consolas", 9), fg='#64748b', bg='#0e1117', width=11, anchor='w')
        self.ui_count.pack(side='left', padx=(0,12))

        self.btns = {}
        for name, txt, clr in [('play','▶','#22c55e'), ('pause','⏸','#f59e0b'), ('stop','■','#ef4444')]:
            b = tk.Label(frame, text=txt, font=("Segoe UI", 8), bg='#1c2128', fg=clr, width=3)
            b.pack(side='left', padx=2, pady=4)
            b.bind('<Button-1>', lambda e, n=name: self.set_state(n))
            self.btns[name] = b

        self.overlay_on = True
        self.overlay_btn = tk.Label(frame, text="◎", font=("Segoe UI", 8), bg='#2d333b', fg='#a78bfa', width=3)
        self.overlay_btn.pack(side='left', padx=2, pady=4)
        self.overlay_btn.bind('<Button-1>', lambda e: self.toggle_overlay())

        close_btn = tk.Label(frame, text="✕", font=("Segoe UI", 8), bg='#1c2128', fg='#64748b', width=3)
        close_btn.pack(side='left', padx=2, pady=4)
        close_btn.bind('<Button-1>', lambda e: self.root.destroy())

        self.root.bind('<Button-1>', self._start_drag)
        self.root.bind('<B1-Motion>', self._on_drag)

        self.thread = threading.Thread(target=self.worker_loop, daemon=True)
        self.thread.start()
        self.refresh_ui()

    def _start_drag(self, e): self._dx, self._dy = e.x, e.y
    def _on_drag(self, e): self.root.geometry(f"+{self.root.winfo_x()+(e.x-self._dx)}+{self.root.winfo_y()+(e.y-self._dy)}")

    def toggle_overlay(self):
        self.overlay_on = not self.overlay_on
        self.overlay_btn.configure(bg='#2d333b' if self.overlay_on else '#1c2128', fg='#a78bfa' if self.overlay_on else '#64748b')

    def set_state(self, action):
        if action == 'play': self.paused = False; self.stopped = False
        elif action == 'pause': self.paused = True; self.stopped = False
        elif action == 'stop': self.paused = False; self.stopped = True
        for name, btn in self.btns.items():
            btn.configure(bg='#2d333b' if name == action else '#1c2128')

    def refresh_ui(self):
        if self.stopped: st, sc = "Stopped", "#ef4444"
        elif self.paused: st, sc = "Paused", "#f59e0b"
        else: st, sc = self.status_text, self.status_color
        self.ui_status.configure(text=st, fg=sc)
        if hasattr(self, 'cooldown') and self.cooldown > 0 and not self.stopped and not self.paused:
            self.ui_count.configure(text=f"{self.cooldown/1000.0:.1f}s wait", fg="#f59e0b")
        else:
            self.ui_count.configure(text=f"{self.total_clicks} clicks", fg="#64748b")
        self.root.after(200, self.refresh_ui)

    def worker_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        threading.Thread(target=start_agentic_bridge, daemon=True).start()

        while True:
            if self.stopped:
                time.sleep(0.5); continue
            try:
                targets = loop.run_until_complete(get_targets_async())
                
                # WHITELIST: Only inject into Antigravity chat pages
                # Skip iframes (sidebar with Rules/MCP/Allowlist), Launchpad, etc.
                pages = [t for t in targets 
                         if t.get('type') == 'page' 
                         and t.get('webSocketDebuggerUrl')
                         and 'Antigravity' in t.get('title', '')]
                self.pages_connected = len(pages)

                if not pages:
                    if not self.paused:
                        self.status_text = "Searching..."
                        self.status_color = "#f59e0b"
                else:
                    if not self.paused:
                        max_cd = 0
                        for p in pages:
                            ws = p.get('webSocketDebuggerUrl')
                            if not ws: continue
                            try:
                                # Force-clear stale heartbeat so new code always injects
                                loop.run_until_complete(_cdp_eval(ws, "if(window.__vc && Date.now()-window.__vchb>8000){window.__vc=false}"))
                                
                                ov_js = f"window.__vcoverlay={'true' if self.overlay_on else 'false'}"
                                loop.run_until_complete(_cdp_eval(ws, ov_js))

                                res = loop.run_until_complete(_cdp_eval(ws, FINDER_JS))
                                if res:
                                    val = res.get('result',{}).get('result',{}).get('value','{}')
                                    try: status = json.loads(val)
                                    except: status = {}
                                    if isinstance(status, dict):
                                        c = status.get('c', 0)
                                        m = status.get('m', '')
                                        inv = status.get('inv', 0)
                                        cd = status.get('cd', 0)
                                        max_cd = max(max_cd, cd)
                                        if c > 0: self.total_clicks = max(self.total_clicks, c)
                                        if m and m != self.last_msg:
                                            self.last_msg = m
                                            print(f"[CLICK] {m}")
                                        self.scan_targets = inv
                                        self.status_text = f"Active ({len(pages)}p) {inv}t"
                                        self.status_color = "#22c55e"
                            except: pass

                            while not command_queue.empty():
                                try:
                                    cmd = command_queue.get_nowait()
                                    if cmd['action'] == 'inject':
                                        js = INJECT_JS % json.dumps(cmd['prompt'])
                                        loop.run_until_complete(_cdp_eval(ws, js))
                                    elif cmd['action'] == 'read_dom':
                                        res = loop.run_until_complete(_cdp_eval(ws, READ_DOM_JS))
                                        val = res.get('result',{}).get('result',{}).get('value','') if res else ''
                                        cmd['res_q'].put(val)
                                except queue.Empty: break
                        self.cooldown = max_cd
            except: pass
            time.sleep(POLL_INTERVAL)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    cleanup_old_processes()
    VegaClickApp().run()
