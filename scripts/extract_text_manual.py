#!/usr/bin/env python3
"""
Manual script to extract text from .docx files
Run this with: python extract_text_manual.py
"""
import zipfile
import xml.etree.ElementTree as ET
import os
import re

def extract_text_from_docx(docx_path):
    """Extract text from a .docx file using zipfile and xml.etree"""
    text = []
    
    try:
        with zipfile.ZipFile(docx_path, 'r') as zip_file:
            if 'word/document.xml' in zip_file.namelist():
                xml_content = zip_file.read('word/document.xml')
                tree = ET.fromstring(xml_content)
                
                # Extract all text elements (w:t tags)
                for elem in tree.iter():
                    if elem.tag.endswith('}t'):
                        if elem.text:
                            text.append(elem.text)
                    elif elem.tag.endswith('}p'):
                        if text and text[-1] != '\n':
                            text.append('\n')
                
    except Exception as e:
        print(f"Error extracting from {docx_path}: {e}")
        return ""
    
    full_text = ''.join(text)
    full_text = re.sub(r'\n{3,}', '\n\n', full_text)
    return full_text

# Process each file
files = [
    ("Manus 1.docx", "Manus_1_text.txt"),
    ("Manus 2.docx", "Manus_2_text.txt"),
    ("Manus 3.docx", "Manus_3_text.txt"),
]

print("=" * 60)
print("DOCX TEXT EXTRACTION")
print("=" * 60)

for docx_file, txt_file in files:
    print(f"\nProcessing: {docx_file}")
    print("-" * 40)
    
    if os.path.exists(docx_file):
        text = extract_text_from_docx(docx_file)
        
        # Save to text file
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f"✓ Extracted {len(text)} characters")
        print(f"✓ Saved to: {txt_file}")
        
        # Show preview
        preview = text[:300].replace('\n', ' ')
        print(f"Preview: {preview}...")
    else:
        print(f"✗ File not found: {docx_file}")

print("\n" + "=" * 60)
print("EXTRACTION COMPLETE")
print("=" * 60)
