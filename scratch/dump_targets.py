import urllib.request, json
targets = []
try:
    data = urllib.request.urlopen('http://127.0.0.1:51734/json', timeout=0.5).read()
    for t in json.loads(data):
        targets.append(t)
except Exception as e:
    pass
for t in targets:
    if t.get('type') in ('page', 'iframe'):
        print(f"Title: {t.get('title')}")
        print(f"URL: {t.get('url')}")
        print("---")
