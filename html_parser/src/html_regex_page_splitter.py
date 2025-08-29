#!/usr/bin/env python3
"""
HTML Page Break Splitter

Splits HTML files based on page break indicators while respecting break-avoidance rules.
This version preserves all whitespace and blank lines to allow exact reconstruction.
"""

import re
import json
import argparse
from pathlib import Path
from typing import List, Dict
import sys
import traceback

sys.setrecursionlimit(10000)


class HTMLPageBreakSplitter:
    def __init__(self):
        # Patterns for page break indicators (case-insensitive)
        self.page_break_patterns = [
            r'page-break-before\s*:\s*always',
            r'page-break-after\s*:\s*always',
            r'break-before\s*:\s*page',
            r'break-after\s*:\s*page',
            r'break-before\s*:\s*always',
            r'break-after\s*:\s*always'
        ]
        
        # Patterns for break avoidance
        self.break_avoidance_patterns = [
            r'page-break-inside\s*:\s*avoid',
            r'break-inside\s*:\s*avoid',
            r'page-break-before\s*:\s*avoid',
            r'page-break-after\s*:\s*avoid',
            r'break-before\s*:\s*avoid',
            r'break-after\s*:\s*avoid'
        ]
        
        self.break_regex = re.compile(
            '|'.join(f'({pattern})' for pattern in self.page_break_patterns),
            re.IGNORECASE
        )
        self.avoid_regex = re.compile(
            '|'.join(f'({pattern})' for pattern in self.break_avoidance_patterns),
            re.IGNORECASE
        )

    def split_html_by_regex(self, html_content: str) -> List[Dict]:
        """Split HTML content into chunks, preserving all whitespace and blank lines."""
        # Find all page break indicators
        break_positions = []

        tag_pattern = re.compile(
            r'<([^>]*style\s*=\s*["\'][^"\']*(?:' +
            '|'.join(self.page_break_patterns) +
            r')[^"\']*["\'][^>]*)>',
            re.IGNORECASE | re.DOTALL
        )

        for match in tag_pattern.finditer(html_content):
            tag_content = match.group(1)
            if not self.avoid_regex.search(tag_content):
                break_positions.append((match.start(), match.group()))

        break_positions.sort(key=lambda x: x[0])

        if not break_positions:
            return [{
                'page': 1,
                'content': html_content,
                'has_break_before': False,
                'break_element_info': 'No breaks found'
            }]

        chunks = []
        last_pos = 0

        for page_num, (break_pos, break_text) in enumerate(break_positions, 1):
            # Include any trailing whitespace before the break in the previous chunk
            temp_break_pos = break_pos
            while temp_break_pos > last_pos and html_content[temp_break_pos - 1] in ('\n', '\r', ' ', '\t'):
                temp_break_pos -= 1

            chunk_content = html_content[last_pos:temp_break_pos]

            chunks.append({
                'page': page_num,
                'content': chunk_content,
                'has_break_before': page_num > 1,
                'break_element_info': {
                    'break_text': break_text[:200],
                    'position': break_pos
                }
            })

            last_pos = break_pos  # Start next chunk at the page break tag

        # Add final chunk
        final_chunk = html_content[last_pos:]
        if final_chunk:
            chunks.append({
                'page': len(break_positions) + 1,
                'content': final_chunk,
                'has_break_before': True,
                'break_element_info': 'Final chunk'
            })

        return chunks

    def process_file(self, input_file: str, output_file: str = None) -> str:
        """Split HTML file and write JSON chunks."""
        input_path = Path(input_file)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        if input_path.suffix.lower() not in ['.html', '.htm']:
            raise ValueError("Input file must be an HTML or HTM file")

        if output_file is None:
            output_file = input_path.stem + '_chunks.json'

        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()

        file_size = len(html_content)

        # Extract <head> if present
        head_match = re.search(r'<head.*?</head>', html_content, re.DOTALL | re.IGNORECASE)
        head_content = head_match.group(0) if head_match else ""

        chunks = self.split_html_by_regex(html_content)

        output_data = {
            'metadata': {
                'original_file': str(input_path),
                'total_pages': len(chunks),
                'file_size': file_size,
                'parsing_method': 'regex',
                'head_content': head_content
            },
            'chunks': chunks
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        return output_file

    def reconstruct_file(self, json_file: str, output_file: str = None) -> str:
        """Reconstruct HTML file from JSON chunks, exactly preserving content."""
        json_path = Path(json_file)
        if not json_path.exists():
            raise FileNotFoundError(f"JSON file not found: {json_file}")

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if output_file is None:
            original_name = Path(data['metadata']['original_file']).stem
            output_file = f"{original_name}_reconstructed.html"

        html_content = ""
        sorted_chunks = sorted(data['chunks'], key=lambda x: x['page'])

        for chunk in sorted_chunks:
            html_content += chunk['content']

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return output_file


def main():
    parser = argparse.ArgumentParser(description='Split HTML files based on page breaks')
    parser.add_argument('input_file', help='HTML/HTM input file or JSON for reconstruction')
    parser.add_argument('-o', '--output', help='Output filename')
    parser.add_argument('-r', '--reconstruct', action='store_true', help='Reconstruct from JSON')
    args = parser.parse_args()

    splitter = HTMLPageBreakSplitter()

    try:
        if args.reconstruct:
            out_file = splitter.reconstruct_file(args.input_file, args.output)
            print(f"Reconstructed HTML file: {out_file}")
        else:
            out_file = splitter.process_file(args.input_file, args.output)
            print(f"Created JSON chunks file: {out_file}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()