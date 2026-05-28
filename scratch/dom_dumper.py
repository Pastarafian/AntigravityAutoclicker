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
        print(f"CDP evaluation failed: {e}")
        return None

async def main():
    targets = await get_targets_async()
    print(f"Found {len(targets)} debug targets.")
    
    js = """
    (function() {
        let p = document.querySelector('.antigravity-agent-side-panel');
        if (p) return p.outerHTML;
        let c = document.getElementById('conversation');
        if (c) return c.outerHTML;
        return document.body.innerHTML; 
    })()
    """
    
    success = False
    for t in targets:
        ws_url = t.get('webSocketDebuggerUrl')
        if not ws_url: continue
        
        try:
            res = await _cdp_eval(ws_url, js)
            if res and 'result' in res and 'result' in res['result']:
                html = res['result']['result'].get('value')
                if html and "antigravity" in html.lower():
                    with open("scratch/dom_dump.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"Successfully dumped DOM from target {t['title']}")
                    success = True
                    break
        except Exception as e:
            pass
            
    if not success:
        print("Failed to get DOM payload.")

if __name__ == '__main__':
    asyncio.run(main())
