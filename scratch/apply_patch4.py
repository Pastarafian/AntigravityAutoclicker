import os
import re

def main():
    target = r"c:\Users\fakej\Documents\VegaClick\vegaclick.py"
    with open(target, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Add 'scheduled tasks' to blocklist
    content = content.replace("'feedback','star',", "'feedback','star', 'scheduled tasks',")

    # 2. Replace getBoxModel with resolveNode + callFunctionOn
    old_click_logic = '''                                    for target in actionable:
                                        await ws.send(json.dumps({
                                            "id": 4, 
                                            "method": "DOM.getBoxModel", 
                                            "params": {"backendNodeId": target["id"]}
                                        }))
                                        
                                        while True:
                                            try:
                                                box_resp = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                                box_data = json.loads(box_resp)
                                                if box_data.get("id") == 4:
                                                    quads = box_data.get("result", {}).get("model", {}).get("border", [])
                                                    if len(quads) >= 8:
                                                        x = (quads[0] + quads[2] + quads[4] + quads[6]) / 4
                                                        y = (quads[1] + quads[3] + quads[5] + quads[7]) / 4
                                                        
                                                        # Bounds Check!
                                                        if chat_bounds:
                                                            if x < chat_bounds['l'] or x > chat_bounds['r'] or y < chat_bounds['t'] or y > chat_bounds['b']:
                                                                self.last_msg = f"Ignored {target['kw']} (out of bounds)"
                                                                self.root.after(0, lambda msg=self.last_msg: self.add_log(msg))
                                                                continue
                                                                
                                                        await ws.send(json.dumps({"id": 101, "method": "Input.dispatchMouseEvent", "params": {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}}))
                                                        await ws.send(json.dumps({"id": 102, "method": "Input.dispatchMouseEvent", "params": {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}}))
                                                        
                                                        self.total_clicks += 1
                                                        self.last_msg = f"Clicked {target['kw']} ({target['name'][:15]})"
                                                        
                                                        # Circuit breaker log
                                                        if target['kw'] == 'retry':
                                                            cbWindow = self.cb_seconds * 1000
                                                            now = time.time() * 1000
                                                            if not hasattr(self, '_vcClickLog'): self._vcClickLog = []
                                                            self._vcClickLog = [cx for cx in self._vcClickLog if now - cx['t'] < cbWindow]
                                                            self._vcClickLog.append({'k': 'retry', 't': now})
                                                            if len(self._vcClickLog) >= self.cb_clicks:
                                                                self.last_msg = "[CIRCUIT BREAKER] Loop detected on retry"
                                                                self._vcClickLog = []
                                                                self.root.after(0, self.toggle_play)
                                                                self.status_text = "PAUSED (Loop Limit)"
                                                                self.status_color = "#ef4444"
                                                                
                                                    break
                                            except asyncio.TimeoutError:
                                                break'''

    new_click_logic = '''                                    for target in actionable:
                                        await ws.send(json.dumps({
                                            "id": 104,
                                            "method": "DOM.resolveNode",
                                            "params": {"backendNodeId": target["id"]}
                                        }))
                                        
                                        obj_id = None
                                        while True:
                                            try:
                                                res_resp = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                                res_data = json.loads(res_resp)
                                                if res_data.get("id") == 104:
                                                    obj_id = res_data.get("result", {}).get("object", {}).get("objectId")
                                                    break
                                            except asyncio.TimeoutError:
                                                break
                                                
                                        if not obj_id:
                                            continue
                                            
                                        # Now call function to click
                                        js_click = """function() {
                                            var r = this.getBoundingClientRect();
                                            if (r.width === 0 && r.height === 0) return "hidden";
                                            if (this.closest('aside, .sidebar, .left-sidebar')) return "sidebar";
                                            this.scrollIntoView({block: 'center'});
                                            this.click();
                                            return "clicked";
                                        }"""
                                        
                                        await ws.send(json.dumps({
                                            "id": 105,
                                            "method": "Runtime.callFunctionOn",
                                            "params": {
                                                "objectId": obj_id,
                                                "functionDeclaration": js_click,
                                                "returnByValue": True
                                            }
                                        }))
                                        
                                        click_res = None
                                        while True:
                                            try:
                                                click_resp = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                                click_data = json.loads(click_resp)
                                                if click_data.get("id") == 105:
                                                    click_res = click_data.get("result", {}).get("result", {}).get("value")
                                                    break
                                            except asyncio.TimeoutError:
                                                break
                                                
                                        if click_res != "clicked":
                                            self.last_msg = f"Ignored {target['kw']} ({click_res})"
                                            self.root.after(0, lambda msg=self.last_msg: self.add_log(msg))
                                            continue
                                            
                                        self.total_clicks += 1
                                        self.last_msg = f"Clicked {target['kw']} ({target['name'][:15]})"
                                        
                                        # Circuit breaker log
                                        if target['kw'] == 'retry':
                                            cbWindow = self.cb_seconds * 1000
                                            now = time.time() * 1000
                                            if not hasattr(self, '_vcClickLog'): self._vcClickLog = []
                                            self._vcClickLog = [cx for cx in self._vcClickLog if now - cx['t'] < cbWindow]
                                            self._vcClickLog.append({'k': 'retry', 't': now})
                                            if len(self._vcClickLog) >= self.cb_clicks:
                                                self.last_msg = "[CIRCUIT BREAKER] Loop detected on retry"
                                                self._vcClickLog = []
                                                self.root.after(0, self.toggle_play)
                                                self.status_text = "PAUSED (Loop Limit)"
                                                self.status_color = "#ef4444"'''
    
    # We need to make sure we replace the EXACT block. Since indentation could be tricky, let's use regex or find the exact start/end.
    # Actually, it's easier to find the old click block by its start and end.
    start_str = '                                    for target in actionable:'
    end_str = '                                                self.status_color = "#ef4444"\n                                                                \n                                                    break\n                                            except asyncio.TimeoutError:\n                                                break'
    
    s_idx = content.find(start_str)
    e_idx = content.find(end_str) + len(end_str)
    
    if s_idx == -1 or e_idx < s_idx:
        print("Failed to find block")
        return
        
    content = content[:s_idx] + new_click_logic + content[e_idx:]
    
    # Also fix the startswith/matching logic to ensure "Allow all" matches "allow" nicely.
    # It already does: if name_lower.startswith(k_kw) ...
    # But let's also remove chat_bounds from the loop if it's not used anymore.
    # It's fine to leave it, it just evaluates JS and does nothing.

    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("Patch 4 Success")

if __name__ == '__main__':
    main()
