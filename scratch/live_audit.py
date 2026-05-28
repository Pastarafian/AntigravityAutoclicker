"""Live audit: dump container classes + all visible button-like text in agent chat."""
import asyncio, json, urllib.request, websockets, sys

# Force UTF-8 stdout
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

async def get_targets():
    all_t = []
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
        if isinstance(r, list): all_t.extend(r)
    return all_t

AUDIT_JS = r"""
(function(){
    var results = {containers: [], buttons: [], kw_matches: []};

    // 1. Find all major panel/container classes
    var allEls = document.querySelectorAll('*');
    var seenCls = new Set();
    for(var i=0; i<allEls.length; i++){
        var el = allEls[i];
        var cls = (el.className || '').toString();
        if(!cls) continue;
        if(/agent|panel|chat|conversation|sidebar|side-panel|agentic/i.test(cls)){
            var key = cls.substring(0, 200);
            if(!seenCls.has(key)){
                seenCls.add(key);
                var r = el.getBoundingClientRect();
                results.containers.push({
                    tag: el.tagName,
                    cls: key,
                    id: el.id || '',
                    w: Math.round(r.width),
                    h: Math.round(r.height),
                    children: el.children.length
                });
            }
        }
    }

    // 2. Find ALL clickable elements and their text
    var btns = document.querySelectorAll('button, [role="button"], [tabindex]');
    for(var j=0; j<btns.length; j++){
        var b = btns[j];
        var r2 = b.getBoundingClientRect();
        if(r2.width < 1 || r2.height < 1) continue;
        var txt = (b.innerText || b.textContent || '').trim().split('\n')[0].trim();
        if(!txt || txt.length > 80) continue;
        var aria = b.getAttribute('aria-label') || '';
        var tooltip = b.getAttribute('data-tooltip-id') || '';
        var role = b.getAttribute('role') || '';
        
        var inPanel = false;
        var p = b;
        for(var k=0; k<25 && p; k++){
            var pc = (p.className||'').toString().toLowerCase();
            var pid = (p.id||'').toLowerCase();
            if(pc.indexOf('antigravity-agent-side-panel') >= 0 || pid === 'conversation' ||
               pc.indexOf('agent-panel') >= 0 || pc.indexOf('agent-side') >= 0 ||
               pc.indexOf('agentic') >= 0 || pc.indexOf('chat-panel') >= 0) {
                inPanel = true; break;
            }
            p = p.parentElement;
        }
        
        results.buttons.push({
            tag: b.tagName,
            text: txt.substring(0, 60),
            role: role,
            aria: aria.substring(0, 40),
            tooltip: tooltip,
            inPanel: inPanel,
            x: Math.round(r2.left),
            y: Math.round(r2.top),
            w: Math.round(r2.width),
            h: Math.round(r2.height)
        });
    }

    // 3. Also find div/span with keyword text
    var kws = ['accept', 'allow', 'trust', 'approve', 'continue', 'run', 'retry', 'ok', 'yes', 'apply', 'relocate', 'send'];
    var spans = document.querySelectorAll('div, span, p');
    for(var s=0; s<spans.length; s++){
        var sp = spans[s];
        var stxt = (sp.innerText || sp.textContent || '').trim().split('\n')[0].trim().toLowerCase();
        if(stxt.length < 2 || stxt.length > 30) continue;
        var matched = false;
        for(var ki=0; ki<kws.length; ki++){
            if(stxt.indexOf(kws[ki]) >= 0){ matched = true; break; }
        }
        if(!matched) continue;
        var sr = sp.getBoundingClientRect();
        if(sr.width < 1 || sr.height < 1) continue;
        var cs;
        try { cs = window.getComputedStyle(sp).cursor; } catch(e){ cs = ''; }
        
        var inP = false;
        var pp = sp;
        for(var pk=0; pk<25 && pp; pk++){
            var ppc = (pp.className||'').toString().toLowerCase();
            var ppid = (pp.id||'').toLowerCase();
            if(ppc.indexOf('antigravity-agent-side-panel') >= 0 || ppid === 'conversation' ||
               ppc.indexOf('agent-panel') >= 0 || ppc.indexOf('agent-side') >= 0 ||
               ppc.indexOf('agentic') >= 0 || ppc.indexOf('chat-panel') >= 0) {
                inP = true; break;
            }
            pp = pp.parentElement;
        }
        
        results.kw_matches.push({
            tag: sp.tagName,
            text: stxt,
            cursor: cs,
            inPanel: inP,
            x: Math.round(sr.left),
            y: Math.round(sr.top)
        });
    }

    return JSON.stringify(results);
})()
"""

async def main():
    targets = await get_targets()
    page_targets = [t for t in targets if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]
    
    print(f"Found {len(targets)} total CDP targets, {len(page_targets)} pages")
    
    for t in page_targets:
        ws_url = t.get('webSocketDebuggerUrl')
        title = t.get('title', '')
        
        if 'Antigravity' not in title and 'antigravity' not in t.get('url','').lower():
            continue

        print(f"\n{'='*70}")
        print(f"TARGET: {title}")
        print(f"{'='*70}")

        try:
            async with websockets.connect(ws_url, max_size=10_000_000, close_timeout=2) as ws:
                await ws.send(json.dumps({
                    "id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": AUDIT_JS, "returnByValue": True}
                }))
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(resp)
                val = data.get('result',{}).get('result',{}).get('value','{}')
                result = json.loads(val)

                print(f"\n--- CONTAINERS ({len(result.get('containers',[]))}) ---")
                for c in result.get('containers', []):
                    print(f"  <{c['tag']}> id=\"{c['id']}\" {c['w']}x{c['h']} children={c['children']}")
                    print(f"    cls=\"{c['cls'][:120]}\"")

                chat_btns = [b for b in result.get('buttons', []) if b['inPanel']]
                other_btns = [b for b in result.get('buttons', []) if not b['inPanel']]
                print(f"\n--- CHAT PANEL BUTTONS ({len(chat_btns)}) ---")
                for b in chat_btns:
                    print(f"  <{b['tag']}> \"{b['text']}\" role={b['role']} aria=\"{b['aria']}\" tip={b['tooltip']} @({b['x']},{b['y']}) {b['w']}x{b['h']}")
                
                print(f"\n--- OTHER BUTTONS ({len(other_btns)}) ---")
                for b in other_btns:
                    print(f"  <{b['tag']}> \"{b['text']}\" role={b['role']} aria=\"{b['aria']}\" tip={b['tooltip']} @({b['x']},{b['y']}) {b['w']}x{b['h']}")

                chat_kw = [p for p in result.get('kw_matches', []) if p['inPanel']]
                other_kw = [p for p in result.get('kw_matches', []) if not p['inPanel']]
                print(f"\n--- KEYWORD DIV/SPAN IN CHAT ({len(chat_kw)}) ---")
                for p in chat_kw:
                    print(f"  <{p['tag']}> \"{p['text']}\" cursor={p['cursor']} @({p['x']},{p['y']})")
                    
                print(f"\n--- KEYWORD DIV/SPAN OUTSIDE CHAT ({len(other_kw)}) ---")
                for p in other_kw:
                    print(f"  <{p['tag']}> \"{p['text']}\" cursor={p['cursor']} @({p['x']},{p['y']})")

                # Save full JSON
                with open("scratch/live_audit.json", "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                print(f"\nFull results saved to scratch/live_audit.json")

        except Exception as e:
            print(f"  ERROR: {e}")

if __name__ == '__main__':
    asyncio.run(main())
