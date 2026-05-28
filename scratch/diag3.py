import asyncio, json, urllib.request, websockets, re

KEYWORDS = [
    ('always allow', 'Always Allow', '#22c55e', 'Always allow tool access'),
    ('allow forever', 'Allow Forever', '#22c55e', 'Allow tool access forever'),
    ('accept all', 'Accept All', '#22c55e', 'Accept all pending code changes'),
    ('allow', 'Allow', '#22c55e', 'Allow tool access for this conversation'),
]

async def test():
    port = open(r'C:\Users\fakej\AppData\Roaming\Antigravity\DevToolsActivePort').read().split('\n')[0]
    resp = urllib.request.urlopen(f'http://127.0.0.1:{port}/json')
    data = json.loads(resp.read())
    ws_url = next(p['webSocketDebuggerUrl'] for p in data if p.get('type') == 'page')
    
    async with websockets.connect(ws_url, max_size=10000000) as ws:
        await ws.send(json.dumps({'id': 1, 'method': 'Accessibility.getFullAXTree'}))
        res = json.loads(await ws.recv())
        nodes = res.get('result', {}).get('nodes', [])
        
        actionable = []
        for node in nodes:
            name = node.get('name', {}).get('value', '')
            role = node.get('role', {}).get('value', '')
            if not name: continue
            if 'allow' in name.lower() or 'run' in name.lower() or 'accept' in name.lower():
                print(f"RAW NODE: name={repr(name)} role={role}")
            
            if role in ["button", "link"] or (role == "StaticText" and ("run" in name_lower or is_numbered)):
                kw_match = None
                for (k_kw, _, _, _) in KEYWORDS:
                    if name_lower.startswith(k_kw) or k_kw == name_lower or (is_numbered and k_kw in name_lower):
                        kw_match = k_kw
                        break
                
                if name_lower == 'submit':
                    kw_match = 'submit'
                    
                if kw_match:
                    if is_numbered and kw_match in name_lower:
                        num_match = re.match(r'^["\'\s]*(\d+)[.)]?\s+', name_lower)
                        if num_match:
                            actionable.append({"name": name, "kw": kw_match, "inject_num": num_match.group(1)})
                            continue
                    actionable.append({"name": name, "kw": kw_match})
        
        print("ACTIONABLE:", json.dumps(actionable, indent=2))

asyncio.run(test())
