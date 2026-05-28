import json
with open(r'C:\Users\fakej\Documents\VegaClick\scratch\nodes5.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
for i, n in enumerate(nodes):
    name = n.get('name', {}).get('value', '').lower().strip()
    if name == 'run':
        print(f"Index: {i}, Role: {n.get('role', {}).get('value', '')}")
        for j in range(max(0, i-5), min(len(nodes), i+5)):
            print(f"  {j}: {nodes[j].get('name', {}).get('value', '')} ({nodes[j].get('role', {}).get('value', '')})")
