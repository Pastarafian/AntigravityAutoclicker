import urllib.request, json, asyncio, websockets
async def dump():
    try:
        data = urllib.request.urlopen('http://127.0.0.1:64818/json').read()
        pages = json.loads(data.decode('utf-8'))
        ws_url = None
        for p in pages:
            if p.get('type') == 'page':
                ws_url = p['webSocketDebuggerUrl']
                break
        if not ws_url: return
        ws = await websockets.connect(ws_url, max_size=10000000)
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': 'document.documentElement.outerHTML', 'returnByValue': True}}))
        while True:
            resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(resp)
            if data.get('id') == 1:
                html = data.get('result', {}).get('result', {}).get('value', '')
                with open('scratch/dom_dump.html', 'w', encoding='utf-8') as f:
                    f.write(html)
                break
    except Exception as e:
        print('Error:', e)
asyncio.run(dump())
