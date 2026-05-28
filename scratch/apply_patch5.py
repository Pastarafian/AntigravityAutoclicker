import os

def main():
    target = r"c:\Users\fakej\Documents\VegaClick\vegaclick.py"
    with open(target, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update JS to check r.left < 300
    old_js = """                                            if (this.closest('.left-sidebar, aside, .sidebar')) return {s: "sidebar"};"""
    new_js = """                                            if (this.closest('.left-sidebar, aside, .sidebar') || r.left < 350) return {s: "sidebar"};"""
    content = content.replace(old_js, new_js)

    # 2. Update blocklist check to also check 'in' for scheduled tasks
    old_block = """                                            if any(b == name_lower for b in blocklist) or any(b in name_lower for b in ['.md', '.py', '.json']):"""
    new_block = """                                            if any(b == name_lower for b in blocklist) or any(b in name_lower for b in ['.md', '.py', '.json', 'scheduled tasks', 'background tasks']):"""
    content = content.replace(old_block, new_block)

    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("Patch 5 Success")

if __name__ == '__main__':
    main()
