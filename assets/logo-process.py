#!/usr/bin/env python3
"""
AstrBot Plugin Logo Processor
Convert any image to 256x256 centered-square PNG.
Usage:
    python logo-process.py <input_image> [output_path]
    Default output: ./logo.png
"""
import sys
import os
from PIL import Image


def process_logo(input_path: str, output_path: str = "logo.png"):
    img = Image.open(input_path)

    # Convert to RGBA for safe handling
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Center-crop to square
    width, height = img.size
    if width != height:
        min_dim = min(width, height)
        left = (width - min_dim) // 2
        top = (height - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))

    # Resize to 256x256
    img = img.resize((256, 256), Image.LANCZOS)

    # Save as PNG
    img.save(output_path, "PNG")
    print(f"Logo saved: {output_path} (256x256 PNG)")
    return output_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.isfile(input_path):
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    output_path = sys.argv[2] if len(sys.argv) > 2 else "logo.png"
    try:
        process_logo(input_path, output_path)
    except Exception as e:
        print(f"Error processing image: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
