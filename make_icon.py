"""Generate icon.ico for RYOS — run once: uv run --with pillow make_icon.py"""
from PIL import Image, ImageDraw

BG    = (30, 42, 58, 255)    # #1e2a3a
BOLT  = (255, 210, 63, 255)  # #FFD23F
SIZES = [16, 24, 32, 48, 64, 128, 256]
SS    = 8   # supersampling — draw 8× then downsample with LANCZOS


def _bolt_pts(s):
    """Lightning bolt polygon, normalized to canvas size s."""
    return [
        (s * 0.62, s * 0.04),   # 1 — top-right
        (s * 0.22, s * 0.55),   # 2 — mid-left
        (s * 0.46, s * 0.55),   # 3 — mid notch right
        (s * 0.38, s * 0.96),   # 4 — bottom tip
        (s * 0.78, s * 0.45),   # 5 — lower-right
        (s * 0.54, s * 0.45),   # 6 — upper notch left
    ]


def draw_icon(size: int) -> Image.Image:
    big = size * SS
    pad = int(big * 0.06)
    r   = int(big * 0.24)

    base = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle(
        [pad, pad, big - pad, big - pad], radius=r, fill=BG
    )
    ImageDraw.Draw(base).polygon(_bolt_pts(big), fill=BOLT)

    return base.resize((size, size), Image.LANCZOS)


master = draw_icon(256)
master.save("icon.ico", format="ICO", sizes=[(s, s) for s in SIZES])
print(f"icon.ico written — {len(SIZES)} sizes: {SIZES}")
