# -*- coding: utf-8 -*-
import urllib.request, re
html = urllib.request.urlopen('http://127.0.0.1:8000/api/lore/html', timeout=30).read().decode('utf-8')
m = re.search(r'<script>(.*?)</script>', html, re.S)
print('script 存在:', bool(m))
if m:
    js = m.group(1)
    print('script 长度:', len(js))
    print(js[:600])
    print('...')
    print(js[-300:])
