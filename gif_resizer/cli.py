"""Command-line interface for gif_resizer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gif_resizer.resizer import FitMode, GifResizer, GifResizerError, Gravity


def parse_size(value: str) -> tuple[int, int]:
    try:
        width_str, height_str = value.lower().split("x")
        return int(width_str), int(height_str)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid size '{value}', expected format WIDTHxHEIGHT (e.g. 128x32)"
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gif-resizer",
        description="Scale and crop animated GIFs to an exact pixel size.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="Input GIF file(s)")
    parser.add_argument(
        "-s",
        "--size",
        required=True,
        type=parse_size,
        help="Target size as WIDTHxHEIGHT, e.g. 128x32",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file (single input only) or output directory (multiple inputs)",
    )
    parser.add_argument(
        "--fit",
        type=FitMode,
        choices=list(FitMode),
        default=FitMode.COVER,
        help=(
            "cover: scale to fill and crop overflow (default); "
            "contain: scale to fit and pad; stretch: ignore aspect ratio"
        ),
    )
    parser.add_argument(
        "--gravity",
        type=Gravity,
        choices=list(Gravity),
        default=Gravity.CENTER,
        help="Where to anchor the crop/pad when the aspect ratio doesn't match",
    )
    parser.add_argument(
        "--background",
        default="black",
        help=(
            "Fill color for padding (--fit contain) and any transparent "
            "pixels already in the source: an ffmpeg color name/hex, or "
            "'transparent' to keep real GIF transparency instead of baking "
            "in a solid color (default: black; note many simple/embedded "
            "GIF decoders don't honor real transparency correctly)"
        ),
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=None,
        help="Optionally resample the animation to this frame rate",
    )
    parser.add_argument(
        "--suffix",
        default="_resized",
        help="Suffix appended to output filenames in batch mode (default: _resized)",
    )
    return parser


def resolve_output_path(input_path: Path, output: Path | None, suffix: str, is_batch: bool) -> Path:
    if output is None:
        return input_path.with_name(f"{input_path.stem}{suffix}{input_path.suffix}")

    if is_batch:
        output.mkdir(parents=True, exist_ok=True)
        return output / input_path.name

    return output


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    is_batch = len(args.inputs) > 1

    if not is_batch and args.output and args.output.is_dir():
        is_batch = True

    try:
        resizer = GifResizer()
    except GifResizerError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    width, height = args.size
    had_error = False

    for input_path in args.inputs:
        output_path = resolve_output_path(input_path, args.output, args.suffix, is_batch)
        try:
            resizer.resize(
                input_path=input_path,
                output_path=output_path,
                width=width,
                height=height,
                fit=args.fit,
                gravity=args.gravity,
                background=args.background,
                fps=args.fps,
            )
            print(f"{input_path} -> {output_path} ({width}x{height})")
        except GifResizerError as error:
            print(f"error: {error}", file=sys.stderr)
            had_error = True

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
