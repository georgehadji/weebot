import urllib.request
import re
import json
import sys
import xml.etree.ElementTree as ET

video_id = 'WuOlqBsDg-w'
url = f'https://www.youtube.com/watch?v={video_id}'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

req = urllib.request.Request(url, headers=headers)
resp = urllib.request.urlopen(req, timeout=15)
html = resp.read().decode('utf-8')
print(f'Page length: {len(html)}')

# Find captionTracks
match = re.search(r'"captionTracks":(\[.*?\])', html)
if not match:
    print('No captionTracks found')
    sys.exit(1)

tracks = json.loads(match.group(1))
print(f'Found {len(tracks)} caption tracks')

# Pick English (US) first, then English, then first available
track = None
for t in tracks:
    if t.get('languageCode') == 'en-US':
        track = t
        break
if not track:
    for t in tracks:
        if t.get('languageCode') == 'en':
            track = t
            break
if not track:
    track = tracks[0]

print(f'Selected: lang={track.get("languageCode")} name={track.get("name", {}).get("simpleText", "")}')

# Fetch the transcript XML
base_url = track['baseUrl']
print(f'Fetching transcript from: {base_url[:80]}...')
treq = urllib.request.Request(base_url, headers=headers)
tresp = urllib.request.urlopen(treq, timeout=15)
txml_bytes = tresp.read()
print(f'Response length: {len(txml_bytes)}')
print(f'Status: {tresp.status}')
print(f'Content-Type: {tresp.headers.get("Content-Type", "unknown")}')
print(f'Response preview (repr): {repr(txml_bytes[:300])}')
txml = txml_bytes.decode('utf-8', errors='replace')

# Parse XML
root = ET.fromstring(txml)
lines = []
for text_el in root.findall('.//text'):
    start = float(text_el.get('start', 0))
    dur = float(text_el.get('dur', 0))
    content = text_el.text or ''
    # Decode HTML entities
    content = content.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'").replace('&quot;', '"')
    lines.append(f'[{start:.1f}s (+{dur:.1f}s)] {content}')

full = '\n'.join(lines)
print(f'Total lines: {len(lines)}')
print(f'Total chars: {len(full)}')

out_path = f'transcript_{video_id}.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(full)
print(f'Saved to {out_path}')
print()
print('--- FIRST 10 LINES ---')
for l in lines[:10]:
    print(l)
