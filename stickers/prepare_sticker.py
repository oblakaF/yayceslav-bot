from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from PIL import Image

CANVAS_SIZE = 512
DEFAULT_CONTENT_SIZE = 480
MAX_STATIC_STICKER_BYTES = 512 * 1024
SUPPORTED_INPUTS = {".png", ".webp", ".jpg", ".jpeg"}


def iter_inputs(paths: list[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in SUPPORTED_INPUTS:
                    yield child
        elif path.is_file() and path.suffix.lower() in SUPPORTED_INPUTS:
            yield path


def trim_transparent(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("image is fully transparent")
    return image.crop(bbox)


def fit_on_canvas(image: Image.Image, content_size: int) -> Image.Image:
    image = trim_transparent(image)
    image.thumbnail((content_size, content_size), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    x = (CANVAS_SIZE - image.width) // 2
    y = (CANVAS_SIZE - image.height) // 2
    canvas.alpha_composite(image, (x, y))
    return canvas


def save_webp_under_limit(image: Image.Image, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)

    image.save(output, "WEBP", lossless=True, method=6)
    size = output.stat().st_size
    if size <= MAX_STATIC_STICKER_BYTES:
        return size

    for quality in (95, 90, 85, 80, 75, 70, 65, 60):
        image.save(output, "WEBP", quality=quality, method=6)
        size = output.stat().st_size
        if size <= MAX_STATIC_STICKER_BYTES:
            return size

    raise ValueError(
        f"cannot reduce {output.name} below 512 KB without stronger compression"
    )


def save_png(image: Image.Image, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)
    size = output.stat().st_size
    if size > MAX_STATIC_STICKER_BYTES:
        raise ValueError(
            f"{output.name} is {size / 1024:.1f} KB; Telegram static sticker limit is 512 KB"
        )
    return size


def prepare_one(source: Path, output_dir: Path, fmt: str, content_size: int) -> Path:
    with Image.open(source) as raw:
        sticker = fit_on_canvas(raw, content_size)

    suffix = ".webp" if fmt == "webp" else ".png"
    output = output_dir / f"{source.stem}{suffix}"

    if fmt == "webp":
        size = save_webp_under_limit(sticker, output)
    else:
        size = save_png(sticker, output)

    print(
        f"OK  {source.name} -> {output} | "
        f"{CANVAS_SIZE}x{CANVAS_SIZE} | {size / 1024:.1f} KB"
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare static images for a Telegram sticker pack."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Image files or directories with PNG/WEBP/JPG/JPEG files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="Destination directory (default: stickers/output).",
    )
    parser.add_argument(
        "--format",
        choices=("webp", "png"),
        default="webp",
        help="Output format (default: webp).",
    )
    parser.add_argument(
        "--content-size",
        type=int,
        default=DEFAULT_CONTENT_SIZE,
        help="Maximum artwork size inside the 512x512 transparent canvas (default: 480).",
    )
    args = parser.parse_args()

    if not 1 <= args.content_size <= CANVAS_SIZE:
        parser.error("--content-size must be between 1 and 512")

    sources = list(iter_inputs(args.inputs))
    if not sources:
        parser.error("no supported images found")

    failures = 0
    for source in sources:
        try:
            prepare_one(source, args.output_dir, args.format, args.content_size)
        except Exception as exc:
            failures += 1
            print(f"ERROR  {source}: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
