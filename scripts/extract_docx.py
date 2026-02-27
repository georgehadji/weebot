#!/usr/bin/env python3
"""Extract text content from .docx files"""

import zipfile
import xml.etree.ElementTree as ET
import os
import re

def extract_text_from_docx(docx_path):
    """Extract all text from a .docx file"""
    try:
        with zipfile.ZipFile(docx_path, 'r') as z:
            xml_content = z.read('word/document.xml')
        tree = ET.fromstring(xml_content)
        
        # Word namespace
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        paragraphs = []
        for para in tree.findall('.//w:p', ns):
            texts = []
            for node in para.findall('.//w:t', ns):
                if node.text:
                    texts.append(node.text)
            if texts:
                paragraphs.append(''.join(texts))
        return '\n'.join(paragraphs)
    except Exception as e:
        return f'Error: {e}'

def extract_python_files(text, docx_name):
    """Extract Python file content from text"""
    # Look for patterns like "filename.py" followed by code blocks
    # or markdown-style code blocks
    
    files = {}
    
    # Pattern 1: Look for ```python blocks
    python_blocks = re.findall(r'```python\n(.*?)```', text, re.DOTALL)
    for i, block in enumerate(python_blocks):
        # Try to find filename before this block
        before_block = text[:text.find(block)]
        filename_match = re.search(r'(\w+\.py)\s*$', before_block[-200:])
        if filename_match:
            files[filename_match.group(1)] = block
        else:
            files[f'block_{i}.py'] = block
    
    # Pattern 2: Look for "File: filename.py" or "filename.py:" patterns
    file_pattern = r'(?:File:|\n)([\w_]+\.py)[\s:]*\n(.*?)(?=\n[\w_]+\.py[\s:]*\n|$)'
    matches = re.findall(file_pattern, text, re.DOTALL)
    for filename, content in matches:
        files[filename] = content.strip()
    
    return files

# Process all docx files
for i in [1, 2, 3]:
    docx_path = f'Manus {i}.docx'
    if os.path.exists(docx_path):
        print(f'\n{"="*60}')
        print(f'Processing: {docx_path}')
        print(f'{"="*60}')
        
        text = extract_text_from_docx(docx_path)
        
        # Save full text for inspection
        with open(f'Manus_{i}_content.txt', 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f'Saved content to Manus_{i}_content.txt ({len(text)} chars)')

print('\nExtraction complete!')
