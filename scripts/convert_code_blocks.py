#!/usr/bin/env python3
"""Convert Markdown triple-backtick code blocks to HTML <pre><code> blocks.

Useful for blog platforms that don't support fenced code blocks.
"""
import re
import sys
import argparse


def convert_code_blocks(md_content: str) -> str:
    """Replace ```language\n...\n``` with <pre><code class="language-LANG">...</code></pre>."""
    pattern = re.compile(r"^```(\w+)\n(.*?)\n```$", re.MULTILINE | re.DOTALL)

    def replacer(match):
        lang = match.group(1)
        code = match.group(2)
        code = code.replace("&", "&amp;")
        code = code.replace("<", "&lt;")
        code = code.replace(">", "&gt;")
        return f'<pre><code class="language-{lang}">\n{code}\n</code></pre>'

    return pattern.sub(replacer, md_content)


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown code blocks to HTML")
    parser.add_argument("input", help="Input markdown file")
    parser.add_argument("--output", "-o", help="Output file (default: overwrite input)")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        content = f.read()

    converted = convert_code_blocks(content)

    output_path = args.output or args.input
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(converted)

    print(f"✅ Converted code blocks in {args.input} → {output_path}")


if __name__ == "__main__":
    main()