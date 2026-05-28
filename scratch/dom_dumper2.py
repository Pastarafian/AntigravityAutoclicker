import asyncio
import json
import urllib.request
import websockets

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
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js_code, "returnByValue": True}}))
            res = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            return res
    except Exception as e:
        return None

async def main():
    targets = await get_targets_async()
    
    js = """
    (function() {
        var results = [];
        var chatPanel = document.querySelector('.antigravity-agent-side-panel') || document.querySelector('#conversation') || document.body;
        
        function walk(root, depth) {
            if(depth > 12) return;
            try {
                var buttons = root.querySelectorAll('button, a, [role="button"], span, div');
                for(var i=0; i<buttons.length; i++) {
                    var e = buttons[i];
                    
                    var isClickable = false;
                    var tag = e.tagName ? e.tagName.toLowerCase() : '';
                    if (tag === 'button' || tag === 'a' || e.getAttribute('role') === 'button') isClickable = true;
                    try {
                        if (window.getComputedStyle(e).cursor === 'pointer') isClickable = true;
                    } catch(ex){}
                    
                    if (!isClickable && !e.className.includes("btn") && !e.className.includes("button")) continue;
                    
                    var t = (e.innerText || e.textContent || e.getAttribute('aria-label') || '').trim();
                    if(t.length < 2 || t.length > 50) continue;
                    
                    // We only want buttons whose text loosely matches things we care about, to avoid noise
                    var tl = t.toLowerCase();
                    if(/accept|allow|trust|approve|continue|run|retry|ok|apply|yes|relocate|send|overview|logs/i.test(tl)) {
                        
                        var parentClasses = [];
                        var curr = e;
                        for(var p=0; p<6; p++) {
                            if(!curr) break;
                            parentClasses.push(curr.className || '');
                            curr = curr.parentElement;
                        }
                        
                        results.push({
                            text: t,
                            tag: e.tagName,
                            cls: e.className,
                            parentClasses: parentClasses
                        });
                    }
                }
                var iframes = root.querySelectorAll('iframe, webview');
                for(var j=0; j<iframes.length; j++) {
                    try {
                        var doc = iframes[j].contentDocument || (iframes[j].contentWindow && iframes[j].contentWindow.document);
                        if(doc) walk(doc, depth+1);
                    } catch(ex){}
                }
            } catch(e){}
        }
        walk(chatPanel, 0);
        return JSON.stringify(results);
    })()
    """
    
    for t in targets:
        ws_url = t.get('webSocketDebuggerUrl')
        if not ws_url: continue
        res = await _cdp_eval(ws_url, js)
        if res and 'result' in res and 'result' in res['result']:
            val = res['result']['result'].get('value')
            if val and val != "[]":
                print(f"RESULTS FROM: {t['title']}")
                with open("scratch/button_dump2.json", "w", encoding="utf-8") as f:
                    import json
                    f.write(json.dumps(json.loads(val), indent=2))
                return
    print("Done scanning.")

if __name__ == '__main__':
    asyncio.run(main())
