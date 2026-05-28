import urllib.request
import json
import asyncio
import websockets

INJECT_JS = """(function() {
    var text = "1";
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
})()"""

async def get_ws():
    data = urllib.request.urlopen('http://127.0.0.1:65415/json').read()
    targets = json.loads(data)
    for t in targets:
        if t.get('type') in ('page', 'iframe') and t.get('webSocketDebuggerUrl'):
            return t['webSocketDebuggerUrl']
    return None

async def main():
    ws_url = await get_ws()
    if not ws_url: return
        
    async with websockets.connect(ws_url, max_size=10_000_000) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": INJECT_JS, "returnByValue": True}}))
        resp = await ws.recv()
        data = json.loads(resp)
        print(json.dumps(data, indent=2))

asyncio.run(main())
