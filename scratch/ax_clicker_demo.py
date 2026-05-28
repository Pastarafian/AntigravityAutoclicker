import asyncio
import json
import urllib.request
import websockets
import time

KEYWORDS = ['accept all', 'allow', 'trust', 'approve', 'continue', 'run', 'retry', 'ok', 'apply', 'yes', 'relocate', 'send', 'overview']

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

async def native_click(ws, x, y):
    # Native CDP Input dispatch
    click_req_down = {
        "id": 101,
        "method": "Input.dispatchMouseEvent",
        "params": {
            "type": "mousePressed",
            "x": x, "y": y,
            "button": "left",
            "clickCount": 1
        }
    }
    click_req_up = {
        "id": 102,
        "method": "Input.dispatchMouseEvent",
        "params": {
            "type": "mouseReleased",
            "x": x, "y": y,
            "button": "left",
            "clickCount": 1
        }
    }
    await ws.send(json.dumps(click_req_down))
    await ws.send(json.dumps(click_req_up))
    print(f"[*] Natively clicked at ({x}, {y})")

async def scan_and_click(ws_url):
    try:
        async with websockets.connect(ws_url, max_size=10_000_000) as ws:
            # Enable required domains
            await ws.send(json.dumps({"id": 1, "method": "DOM.enable"}))
            await ws.send(json.dumps({"id": 2, "method": "Accessibility.enable"}))
            
            print("[+] Connected and enabled DOM & Accessibility domains.")
            
            while True:
                # 1. Fetch full AX tree
                await ws.send(json.dumps({"id": 3, "method": "Accessibility.getFullAXTree"}))
                
                nodes = []
                while True:
                    resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    data = json.loads(resp)
                    if data.get("id") == 3:
                        nodes = data.get("result", {}).get("nodes", [])
                        break
                
                # 2. Filter for actionable buttons
                actionable = []
                for node in nodes:
                    role = node.get("role", {}).get("value")
                    name = node.get("name", {}).get("value", "")
                    node_id = node.get("backendDOMNodeId")
                    
                    if role in ["button", "link", "StaticText"] and name:
                        name_lower = name.lower()
                        # Direct keyword match
                        if any(kw in name_lower for kw in KEYWORDS) or role == "button":
                            actionable.append({"name": name, "id": node_id})
                
                if actionable:
                    print(f"[*] Found {len(actionable)} potential targets. Resolving coordinates...")
                    
                    for target in actionable:
                        # 3. Get Bounding Box native to the DOM backend node
                        await ws.send(json.dumps({
                            "id": 4, 
                            "method": "DOM.getBoxModel", 
                            "params": {"backendNodeId": target["id"]}
                        }))
                        
                        box_resp = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        box_data = json.loads(box_resp)
                        
                        if box_data.get("id") == 4 and "result" in box_data:
                            quads = box_data["result"].get("model", {}).get("border", [])
                            if len(quads) >= 8:
                                # quads: [x1, y1, x2, y2, x3, y3, x4, y4]
                                x = (quads[0] + quads[2] + quads[4] + quads[6]) / 4
                                y = (quads[1] + quads[3] + quads[5] + quads[7]) / 4
                                
                                print(f"[+] Target '{target['name']}' resolved to ({x}, {y})")
                                # Uncomment to actually perform the click:
                                # await native_click(ws, x, y)
                
                await asyncio.sleep(2.0)
                
    except Exception as e:
        print(f"[-] Disconnected or Error: {e}")

async def main():
    targets = await get_targets_async()
    for t in targets:
        ws_url = t.get('webSocketDebuggerUrl')
        if not ws_url: continue
        if "antigravity" not in t.get("title", "").lower() and "antigravity" not in t.get("url", "").lower():
            continue
            
        print(f"Attaching AX Scanner to: {t['title']}")
        await scan_and_click(ws_url)
        break

if __name__ == '__main__':
    asyncio.run(main())
