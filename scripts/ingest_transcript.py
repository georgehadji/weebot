from youtube_transcript_api import YouTubeTranscriptApi
import json

video_id = "WuOlqBsDg-w"
api = YouTubeTranscriptApi()

# Fetch the manual English transcript
transcript = api.fetch(video_id, languages=['en-US'])

# Build structured data
segments = []
for seg in transcript:
    segments.append({
        "text": seg.text,
        "start": round(seg.start, 2),
        "duration": round(seg.duration, 3)
    })

# Save full transcript
output = {
    "video_id": video_id,
    "url": f"https://youtu.be/{video_id}",
    "title": "Agent Team vs Agent Swarm - System Design & Testing",
    "language": "en-US",
    "segment_count": len(segments),
    "segments": segments
}

path = "E:/Documents/Vibe-Coding/weebot/data/agent_team_vs_swarm_transcript.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Saved {len(segments)} segments to JSON")

# Also create JSONL training data with ~400 word chunks
full_text = " ".join(seg.text for seg in transcript)
words = full_text.split()
print(f"Total words: {len(words)}")

chunks = []
chunk_size = 400
for i in range(0, len(words), chunk_size):
    chunk_words = words[i:i+chunk_size]
    chunk_text = " ".join(chunk_words)
    chunks.append({
        "instruction": "Explain the concepts from this transcript about Agent Team vs Agent Swarm system design.",
        "input": "",
        "output": chunk_text,
        "source": f"https://youtu.be/{video_id}",
        "chunk_index": len(chunks)
    })

jsonl_path = "E:/Documents/Vibe-Coding/weebot/data/agent_team_vs_swarm.jsonl"
with open(jsonl_path, "w", encoding="utf-8") as f:
    for chunk in chunks:
        f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

print(f"Saved {len(chunks)} chunks to JSONL")
