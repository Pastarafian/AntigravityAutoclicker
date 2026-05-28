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

async def get_ax_tree(ws_url):
    try:
        async with websockets.connect(ws_url, max_size=10_000_000) as ws:
            await ws.send(json.dumps({"id": 1, "method": "DOM.enable"}))
            await ws.recv()
            await ws.send(json.dumps({"id": 2, "method": "Accessibility.enable"}))
            await ws.recv()
            await ws.send(json.dumps({"id": 3, "method": "Accessibility.getFullAXTree"}))
            while True:
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(resp)
                if data.get("id") == 3:
                    return data.get("result", {}).get("nodes", [])
    except Exception as e:
        return []

async def main():
    targets = await get_targets_async()
    for t in targets:
        ws_url = t.get('webSocketDebuggerUrl')
        if not ws_url: continue
        if "antigravity" not in t.get("title", "").lower() and "antigravity" not in t.get("url", "").lower():
            continue
            
        nodes = await get_ax_tree(ws_url)
        
        matches = []
        for node in nodes:
            role = node.get("role", {}).get("value")
            name = node.get("name", {}).get("value", "")
            if role in ["button", "link", "StaticText"] and name:
                matches.append({"role": role, "name": name, "id": node.get("backendDOMNodeId")})
                
        with open("scratch/ax_dump.json", "w", encoding="utf-8") as f:
            json.dump(matches, f, indent=2)
        print(f"Saved {len(matches)} accessible nodes to scratch/ax_dump.json")
            
if __name__ == '__main__':
    asyncio.run(main())
