with open('transcript_WuOlqBsDg-w.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

chunk_size = 40
chunks = []
for i in range(0, len(lines), chunk_size):
    chunk_lines = lines[i:i+chunk_size]
    chunk_text = ''.join(chunk_lines).strip()
    start_time = chunk_lines[0].split(']')[0].lstrip('[')
    chunks.append((start_time, chunk_text))

for idx, (start, text) in enumerate(chunks):
    print(f'CHUNK {idx+1}|{start}|{len(text)}')
    print(text)
    print('---END---')
