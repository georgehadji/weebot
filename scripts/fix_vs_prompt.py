import re

with open('weebot/models/structured_output.py', encoding='utf-8') as f:
    content = f.read()

# Replace the VS_FALLBACK_PROMPT assignment to escape JSON braces for .format()
old_prompt = (
    'VS_FALLBACK_PROMPT: str = \\\n'
    '    "You are a helpful assistant. For the given task, generate a set of {k} DISTINCT " \\\n'
    '    "candidate responses that together approximate the full distribution of good answers.\\n\\n" \\\n'
    '    "Return ONLY valid JSON, no markdown:\\n" \\\n'
    '    \'{"responses": [{"text": "<candidate>", "probability": <0..1>}, ...]}\\n\\n\' \\\n'
    '    "- Each candidate must be meaningfully different from the others.\\n" \\\n'
    '    \'"probability" is your estimate of how typical/likely each candidate is.\\n\' \\\n'
    '    "{threshold_clause}"'
)

new_prompt = (
    'VS_FALLBACK_PROMPT: str = \\\n'
    '    "You are a helpful assistant. For the given task, generate a set of {k} DISTINCT " \\\n'
    '    "candidate responses that together approximate the full distribution of good answers.\\n\\n" \\\n'
    '    "Return ONLY valid JSON, no markdown:\\n" \\\n'
    '    \'{{"responses": [{{"text": "<candidate>", "probability": <0..1>}}, ...]}}\\n\\n\' \\\n'
    '    "- Each candidate must be meaningfully different from the others.\\n" \\\n'
    '    \'"probability" is your estimate of how typical/likely each candidate is.\\n\' \\\n'
    '    "{threshold_clause}"'
)

if old_prompt in content:
    content = content.replace(old_prompt, new_prompt)
    with open('weebot/models/structured_output.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('REPLACED')
else:
    print('NOT FOUND')
    # Debug: show what's actually in the file
    idx = content.find('VS_FALLBACK_PROMPT')
    if idx >= 0:
        print('Found at', idx)
        print(repr(content[idx:idx+500]))
