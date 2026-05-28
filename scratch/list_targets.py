import urllib.request, json
try:
    data = urllib.request.urlopen('http://127.0.0.1:64818/json').read()
    pages = json.loads(data.decode('utf-8'))
    for p in pages:
        print('Title: ' + str(p.get('title')) + ' - URL: ' + str(p.get('url')) + ' - WSDU: ' + str(p.get('webSocketDebuggerUrl')))
except Exception as e:
    print('Error:', e)
