import os
import re

def main():
    target = r"c:\Users\fakej\Documents\VegaClick\vegaclick.py"
    with open(target, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update get_targets_async
    new_get_targets = '''async def get_targets_async():
    all_targets = []
    async def probe(port):
        try:
            loop = asyncio.get_event_loop()
            import urllib.request
            data = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=0.3).read()),
                timeout=0.5)
            return json.loads(data)
        except: return []
        
    ports_to_try = list(range(9222, 9242))
    import os
    appdata = os.environ.get('APPDATA', '')
    if appdata:
        dtp = os.path.join(appdata, 'Antigravity', 'DevToolsActivePort')
        if os.path.exists(dtp):
            try:
                with open(dtp, 'r') as f:
                    port_str = f.readline().strip()
                    if port_str.isdigit():
                        ports_to_try.append(int(port_str))
            except: pass

    results = await asyncio.gather(*[probe(p) for p in set(ports_to_try)], return_exceptions=True)
    for r in results:
        if isinstance(r, list): all_targets.extend(r)
    return all_targets'''
    
    # Replace the old get_targets_async function
    content = re.sub(r'async def get_targets_async\(\):.*?return all_targets', new_get_targets, content, flags=re.DOTALL)

    # 2. Update page filtering in async_worker_loop
    # Replace: and ('Antigravity' in t.get('title', '') or 'antigravity-panel' in t.get('url', ''))]
    # With: and ('Antigravity' in t.get('title', '') or 'antigravity-panel' in t.get('url', '') or '127.0.0.1' in t.get('url', ''))]
    content = content.replace(
        "and ('Antigravity' in t.get('title', '') or 'antigravity-panel' in t.get('url', ''))]",
        "and ('Antigravity' in t.get('title', '') or 'antigravity-panel' in t.get('url', '') or '127.0.0.1' in t.get('url', ''))]"
    )

    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)

    print("Success")

if __name__ == '__main__':
    main()
