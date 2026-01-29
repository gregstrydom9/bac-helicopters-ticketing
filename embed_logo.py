#!/usr/bin/env python3
"""
Logo Embedding Script for BAC Helicopters Ticketing System

This script reads a logo file, base64-encodes it, and embeds it
into main_template.py to create main.py.

Usage:
    python embed_logo.py [logo_path]

If logo_path is not provided, it looks for common logo filenames:
    - BAC_Logo_Helicopter_Print_White.png
    - logo.png
    - BAC_logo.png
"""

import base64
import sys
from pathlib import Path

# Common logo filenames to try
LOGO_CANDIDATES = [
    "BAC_Logo_Helicopter_Print_White.png",
    "logo.png",
    "BAC_logo.png",
    "logo_white.png",
]

TEMPLATE_FILE = "main_template.py"
OUTPUT_FILE = "main.py"
PLACEHOLDER = "%%BASE64_LOGO%%"


def find_logo():
    """Find a logo file in the current directory."""
    # Try both current working directory and script directory
    search_dirs = [Path.cwd(), Path(__file__).parent]

    print(f"Current working directory: {Path.cwd()}")
    print(f"Script directory: {Path(__file__).parent}")
    print(f"Directory contents: {list(Path.cwd().glob('*'))}")

    # Check command line argument first
    if len(sys.argv) > 1:
        logo_path = Path(sys.argv[1])
        if logo_path.exists():
            return logo_path
        else:
            print(f"Warning: Specified logo file not found: {logo_path}")

    # Try common filenames in both directories
    for base_dir in search_dirs:
        for filename in LOGO_CANDIDATES:
            logo_path = base_dir / filename
            print(f"Checking: {logo_path} - exists: {logo_path.exists()}")
            if logo_path.exists():
                return logo_path

    return None


def embed_logo():
    """Read logo, encode to base64, and embed in template."""
    # Use current working directory for Railway compatibility
    base_dir = Path.cwd()
    template_path = base_dir / TEMPLATE_FILE
    output_path = base_dir / OUTPUT_FILE

    print(f"Template path: {template_path} - exists: {template_path.exists()}")
    print(f"Output path: {output_path}")

    # Check template exists
    if not template_path.exists():
        print(f"Error: Template file not found: {template_path}")
        sys.exit(1)

    # Read template
    template_content = template_path.read_text(encoding='utf-8')

    # Find and encode logo
    logo_path = find_logo()
    if logo_path:
        print(f"Found logo: {logo_path}")
        logo_data = logo_path.read_bytes()
        logo_base64 = base64.b64encode(logo_data).decode('utf-8')
        print(f"Logo encoded: {len(logo_base64)} characters ({len(logo_data)} bytes)")
    else:
        print("Warning: No logo file found. Using empty placeholder.")
        print(f"Looked for: {', '.join(LOGO_CANDIDATES)}")
        logo_base64 = ""

    # Replace placeholder
    if PLACEHOLDER not in template_content:
        print(f"Warning: Placeholder '{PLACEHOLDER}' not found in template")
        output_content = template_content
    else:
        output_content = template_content.replace(PLACEHOLDER, logo_base64)
        print(f"Placeholder replaced in template")

    # Write output
    output_path.write_text(output_content, encoding='utf-8')
    print(f"Generated: {output_path}")

    # Verify the file was written correctly
    written_content = output_path.read_text(encoding='utf-8')
    if "%%BASE64_LOGO%%" in written_content:
        print("ERROR: Placeholder still in output file!")
    else:
        print(f"SUCCESS: Logo embedded, main.py size: {len(written_content)} chars")
        # Print a snippet around BASE64_LOGO
        idx = written_content.find('BASE64_LOGO = "')
        if idx != -1:
            snippet = written_content[idx:idx+100]
            print(f"Snippet: {snippet}...")

    # Verify
    if logo_base64:
        # Quick verification
        try:
            decoded = base64.b64decode(logo_base64)
            assert decoded == logo_data
            print("Logo verification: OK")
        except Exception as e:
            print(f"Logo verification failed: {e}")


if __name__ == '__main__':
    embed_logo()
