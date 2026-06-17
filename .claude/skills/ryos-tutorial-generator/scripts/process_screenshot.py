#!/usr/bin/env python3
"""
process_screenshot.py — turn a raw desktop screenshot into a clean, doc-ready PNG.

Crops a screenshot to the RYOS window (or a dialog), optionally auto-trims a uniform
border, downscales to a maximum width, and writes an optimized PNG. Run it on every
capture so the tutorial's images are uniform in size and quality.

Usage:
  # Crop to explicit pixel coordinates (left top right bottom), then cap width at 1000:
  python process_screenshot.py raw.png out.png --crop 120 80 1020 730 --max-width 1000

  # Auto-trim a uniform border (good for a dialog sitting on a solid backdrop):
  python process_screenshot.py raw.png out.png --autotrim --max-width 800

  # Just downscale, no cropping:
  python process_screenshot.py raw.png out.png --max-width 1000

Requires Pillow:  pip install Pillow --break-system-packages
"""
import argparse
import sys

try:
    from PIL import Image, ImageChops
except ImportError:
    sys.exit("Pillow is required. Install with: pip install Pillow --break-system-packages")


def autotrim(img, tol=12):
    """Trim a uniform border by comparing against the top-left pixel's color."""
    rgb = img.convert("RGB")
    bg = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    diff = ImageChops.difference(rgb, bg)
    # Amplify so near-background pixels still count as background within tolerance.
    diff = ImageChops.add(diff, diff, 2.0, -tol)
    bbox = diff.getbbox()
    return img.crop(bbox) if bbox else img


def main():
    p = argparse.ArgumentParser(description="Crop/trim/downscale a screenshot for docs.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--crop", nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
                   help="Crop box in pixels.")
    p.add_argument("--autotrim", action="store_true",
                   help="Trim a uniform border (applied after --crop if both given).")
    p.add_argument("--tol", type=int, default=12,
                   help="Autotrim color tolerance (default 12).")
    p.add_argument("--max-width", type=int, default=1000,
                   help="Downscale so width <= this (default 1000; 0 disables).")
    p.add_argument("--pad", type=int, default=0,
                   help="Add N px of white padding around the result (default 0).")
    args = p.parse_args()

    img = Image.open(args.input)

    if args.crop:
        l, t, r, b = args.crop
        img = img.crop((l, t, r, b))

    if args.autotrim:
        img = autotrim(img, tol=args.tol)

    if args.max_width and img.width > args.max_width:
        h = round(img.height * args.max_width / img.width)
        img = img.resize((args.max_width, h), Image.LANCZOS)

    if args.pad > 0:
        canvas = Image.new("RGB", (img.width + 2 * args.pad, img.height + 2 * args.pad),
                           (255, 255, 255))
        canvas.paste(img.convert("RGB"), (args.pad, args.pad))
        img = canvas

    img = img.convert("RGB")
    img.save(args.output, "PNG", optimize=True)
    print(f"wrote {args.output}  ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
