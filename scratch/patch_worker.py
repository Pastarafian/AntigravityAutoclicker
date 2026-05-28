import os

AX_WORKER = '''
    def worker_loop(self):
        debug_log("Worker loop starting")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        threading.Thread(target=start_agentic_bridge, daemon=True).start()
        debug_log("Agentic bridge thread spawned")
        loop.run_until_complete(self.async_worker_loop())

    async def async_worker_loop(self):
        import websockets
        active_connections = {}
        
        auto_scroll_js = """
        (function() {
            var panels = document.querySelectorAll('.antigravity-agent-side-panel, #conversation');
            if(panels.length === 0) panels = document.querySelectorAll('*');
            for(var i=0; i<panels.length; i++){
                var el = panels[i];
                if(el.scrollHeight <= el.clientHeight + 80) continue;
                var cs = window.getComputedStyle(el);
                if(cs.overflowY !== 'auto' && cs.overflowY !== 'scroll') continue;
                var rect = el.getBoundingClientRect();
                if(rect.width < 150 || rect.height < 150) continue;
                var distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
                if(distFromBottom > 50){
                    el.scrollTop = el.scrollHeight;
                }
            }
        })()
        """

        while True:
            try:
                targets = await get_targets_async()
                pages = [t for t in targets 
                         if t.get('type') in ('page', 'iframe') 
                         and t.get('webSocketDebuggerUrl')
                         and ('Antigravity' in t.get('title', '') or 'antigravity-panel' in t.get('url', ''))]
                self.pages_connected = len(pages)

                if not pages:
                    if self.active:
                        self.status_text = "Searching..."
                        self.status_color = "#f59e0b"
                        self.search_ticks += 1
                        if self.search_ticks == 25:
                            self.root.after(0, self.prompt_restart)
                    else:
                        self.status_text = "Inactive"
                        self.status_color = "#64748b"
                        
                    for ws in list(active_connections.values()):
                        await ws.close()
                    active_connections.clear()
                else:
                    self.search_ticks = 0
                    a_count = 0; w_count = 0; c_count = 0
                    max_cd = 0

                    if self.active:
                        for p in pages:
                            ws_url = p.get('webSocketDebuggerUrl')
                            if not ws_url: continue
                            
                            if ws_url not in active_connections:
                                try:
                                    ws = await websockets.connect(ws_url, max_size=10_000_000, close_timeout=1)
                                    await ws.send(json.dumps({"id": 1, "method": "DOM.enable"}))
                                    await ws.send(json.dumps({"id": 2, "method": "Accessibility.enable"}))
                                    active_connections[ws_url] = ws
                                except Exception:
                                    continue
                                    
                            ws = active_connections[ws_url]
                            
                            try:
                                # Auto scroll
                                if not self.scroll_paused:
                                    await ws.send(json.dumps({"id": 5, "method": "Runtime.evaluate", "params": {"expression": auto_scroll_js}}))

                                # Process agentic bridge queues
                                while not command_queue.empty():
                                    try:
                                        cmd = command_queue.get_nowait()
                                        if cmd['action'] == 'inject':
                                            js = INJECT_JS % json.dumps(cmd['prompt'])
                                            await ws.send(json.dumps({"id": 6, "method": "Runtime.evaluate", "params": {"expression": js}}))
                                        elif cmd['action'] == 'read_dom':
                                            await ws.send(json.dumps({"id": 7, "method": "Runtime.evaluate", "params": {"expression": READ_DOM_JS, "returnByValue": True}}))
                                    except Exception: break

                                # Get AX Tree
                                await ws.send(json.dumps({"id": 3, "method": "Accessibility.getFullAXTree"}))
                                nodes = []
                                while True:
                                    try:
                                        resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                                        data = json.loads(resp)
                                        
                                        if data.get("id") == 7:
                                            val = data.get('result',{}).get('result',{}).get('value','')
                                            for q_cmd in command_queue.queue:
                                                if q_cmd.get('action') == 'read_dom':
                                                    q_cmd['res_q'].put(val)
                                                    
                                        if data.get("id") == 3:
                                            nodes = data.get("result", {}).get("nodes", [])
                                            break
                                    except asyncio.TimeoutError:
                                        break

                                dots = False
                                all_matched = 0
                                actionable = []
                                
                                blocklist = ['delete','remove','uninstall','format','reset','sign out','log out','close','discard','reject','deny','dismiss','erase','drop','run and debug','go back','go forward','more actions','always run','running','runner','run extension','run_cli','rescue run','rescue','allowlist','restart','reload','rules','mcp','feedback','star', '.md', '.py', '.js', '.json', '.html']
                                
                                for node in nodes:
                                    role = node.get("role", {}).get("value")
                                    name = node.get("name", {}).get("value", "")
                                    node_id = node.get("backendDOMNodeId")
                                    
                                    if name and role in ["StaticText", "button", "link"]:
                                        name_lower = name.lower().strip()
                                        
                                        if name_lower in ['...', '..', '.', '\u2026', 'stop generating', 'cancel', 'stop']:
                                            dots = True
                                            
                                        if role in ["button", "link"] or (role == "StaticText" and "run" in name_lower):
                                            if any(b == name_lower for b in blocklist) or any(b in name_lower for b in ['.md', '.py', '.json']):
                                                continue
                                                
                                            kw_match = None
                                            for (k_kw, _, _, _) in KEYWORDS:
                                                if name_lower.startswith(k_kw) or k_kw == name_lower:
                                                    kw_match = k_kw
                                                    break
                                            
                                            if kw_match and self.enabled.get(kw_match, True):
                                                actionable.append({"name": name, "id": node_id, "kw": kw_match})
                                                all_matched += 1

                                if getattr(self, '_pending_reset', False):
                                    self.total_clicks = 0
                                    self._pending_reset = False

                                if actionable:
                                    for target in actionable:
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
                                                                
                                                        self.root.after(0, self.flash_click)
                                                        self.root.after(0, lambda msg=self.last_msg: self.add_log(msg))
                                                        
                                                        if self.overlay_on:
                                                            ripple_js = f"""
                                                            (function(){{
                                                                var dot = document.createElement('div');
                                                                dot.style.cssText = 'position:fixed;pointer-events:none;z-index:999999;border-radius:50%;left:{x-16}px;top:{y-16}px;width:32px;height:32px;border:3px solid rgba(168,85,247,0.9);background:rgba(168,85,247,0.3);transition:transform 0.5s ease-out, opacity 0.5s ease-out;transform:scale(0.5);opacity:1';
                                                                document.body.appendChild(dot);
                                                                requestAnimationFrame(function() {{ dot.style.transform = 'scale(2.5)'; dot.style.opacity = '0'; }});
                                                                setTimeout(function() {{ dot.remove() }}, 600);
                                                            }})()
                                                            """
                                                            await ws.send(json.dumps({"id": 5, "method": "Runtime.evaluate", "params": {"expression": ripple_js}}))
                                                    break
                                            except asyncio.TimeoutError:
                                                break
                                                
                                    max_cd = self.click_delay
                                    await asyncio.sleep(self.click_delay / 1000.0)

                                if dots: a_count += 1
                                elif all_matched > 0: w_count += 1
                                else: c_count += 1
                                
                            except websockets.exceptions.ConnectionClosed:
                                del active_connections[ws_url]
                            except Exception:
                                pass

                        self.cooldown = max_cd
                        self._pages_total = len(pages)
                        self._page_states = (a_count, w_count, c_count)
                        
                        if a_count > 0 or w_count > 0:
                            self._last_busy_time = time.time()
                            self._idle_alerted = False
                        elif self.idle_alert_minutes > 0 and not self._idle_alerted:
                            idle_seconds = time.time() - self._last_busy_time
                            if idle_seconds >= self.idle_alert_minutes * 60:
                                self._idle_alerted = True
                                self.root.after(0, self._play_idle_alert)
                                self.root.after(0, lambda: self.add_log(f'Idle alert - agent idle for {self.idle_alert_minutes}min'))
                        self.status_text = 'states'
                    else:
                        self.status_text = "Inactive"
                        self.status_color = "#64748b"
            except Exception:
                pass
                
            await asyncio.sleep(POLL_INTERVAL)
'''

with open("vegaclick_ax.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Remove FINDER_JS block (lines 370-376)
start_idx = content.find("# ═══════════════════════════════════════════════════════════════\n# VegaClick v16")
end_idx = content.find("FINDER_JS = _f.read()")
if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + "# ═══════════════════════════════════════════════════════════════\n# VegaClick v17 AX Scanner\n# ═══════════════════════════════════════════════════════════════\nimport os\n" + content[end_idx + len("FINDER_JS = _f.read()"): ]

# 2. Replace worker_loop
start_loop = content.find("    def worker_loop(self):")
end_loop = content.find("    def run(self):")

if start_loop != -1 and end_loop != -1:
    content = content[:start_loop] + AX_WORKER + "\n" + content[end_loop:]

with open("vegaclick_ax.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Migration completed.")
