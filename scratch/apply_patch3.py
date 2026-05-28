import os

def main():
    target = r"c:\Users\fakej\Documents\VegaClick\vegaclick.py"
    with open(target, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Insert chat_bounds evaluation before getFullAXTree
    ax_fetch_orig = '''                                # Get AX Tree
                                await ws.send(json.dumps({"id": 3, "method": "Accessibility.getFullAXTree"}))
                                nodes = []
                                while True:'''
                                
    ax_fetch_new = '''                                # Get chat bounds to prevent clicking sidebar tasks
                                bounds_js = """(function(){
                                    var chat = document.querySelector('#conversation, .conversation, .chat-container, .chat, main, .antigravity-agent-side-panel');
                                    if(!chat) return {l: 0, r: window.innerWidth * 0.75, t: 0, b: window.innerHeight};
                                    var r = chat.getBoundingClientRect();
                                    return {l: r.left - 20, r: r.right + 20, t: r.top - 20, b: r.bottom + 20}; // adding 20px padding
                                })()"""
                                await ws.send(json.dumps({"id": 99, "method": "Runtime.evaluate", "params": {"expression": bounds_js, "returnByValue": True}}))

                                # Get AX Tree
                                await ws.send(json.dumps({"id": 3, "method": "Accessibility.getFullAXTree"}))
                                nodes = []
                                chat_bounds = None
                                while True:'''
    content = content.replace(ax_fetch_orig, ax_fetch_new)

    # 2. Capture chat_bounds from id: 99 response
    # We'll insert it right before: if data.get("id") == 3:
    id3_orig = '''                                        if data.get("id") == 3:
                                            nodes = data.get("result", {}).get("nodes", [])
                                            break'''
    id3_new = '''                                        if data.get("id") == 99:
                                            chat_bounds = data.get("result", {}).get("result", {}).get("value")
                                            
                                        if data.get("id") == 3:
                                            nodes = data.get("result", {}).get("nodes", [])
                                            break'''
    content = content.replace(id3_orig, id3_new)

    # 3. Add bounds checking before clicking
    click_orig = '''                                                        x = (quads[0] + quads[2] + quads[4] + quads[6]) / 4
                                                        y = (quads[1] + quads[3] + quads[5] + quads[7]) / 4
                                                        
                                                        await ws.send(json.dumps({"id": 101, "method": "Input.dispatchMouseEvent", "params": {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}}))'''
                                                        
    click_new = '''                                                        x = (quads[0] + quads[2] + quads[4] + quads[6]) / 4
                                                        y = (quads[1] + quads[3] + quads[5] + quads[7]) / 4
                                                        
                                                        # Bounds Check!
                                                        if chat_bounds:
                                                            if x < chat_bounds['l'] or x > chat_bounds['r'] or y < chat_bounds['t'] or y > chat_bounds['b']:
                                                                self.last_msg = f"Ignored {target['kw']} (out of bounds)"
                                                                self.root.after(0, lambda msg=self.last_msg: self.add_log(msg))
                                                                continue
                                                                
                                                        await ws.send(json.dumps({"id": 101, "method": "Input.dispatchMouseEvent", "params": {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}}))'''
    content = content.replace(click_orig, click_new)

    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("Patch 3 Success")

if __name__ == '__main__':
    main()
