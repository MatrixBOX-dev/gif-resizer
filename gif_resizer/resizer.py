"""Resize and crop animated GIFs to an exact pixel size using ffmpeg.

ffmpeg's filter graph runs on every frame of an animated GIF automatically,
so a single invocation handles the whole animation without decoding and
re-encoding frames by hand.
"""

from __future__ import annotations

import shutil
import subprocess
from enum import StrEnum
from pathlib import Path


class FitMode(StrEnum):
    COVER = "cover"
    CONTAIN = "contain"
    STRETCH = "stretch"


class Gravity(StrEnum):
    CENTER = "center"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"


# Offsets for the `crop` filter: the crop window sits inside a larger,
# already-scaled frame, so "top" means pinning the window's y to 0.
_CROP_OFFSETS: dict[Gravity, tuple[str, str]] = {
    Gravity.CENTER: ("(in_w-out_w)/2", "(in_h-out_h)/2"),
    Gravity.TOP: ("(in_w-out_w)/2", "0"),
    Gravity.BOTTOM: ("(in_w-out_w)/2", "(in_h-out_h)"),
    Gravity.LEFT: ("0", "(in_h-out_h)/2"),
    Gravity.RIGHT: ("(in_w-out_w)", "(in_h-out_h)/2"),
    Gravity.TOP_LEFT: ("0", "0"),
    Gravity.TOP_RIGHT: ("(in_w-out_w)", "0"),
    Gravity.BOTTOM_LEFT: ("0", "(in_h-out_h)"),
    Gravity.BOTTOM_RIGHT: ("(in_w-out_w)", "(in_h-out_h)"),
}

# Offsets for the `overlay` filter: the scaled frame sits inside a larger
# canvas, so "top" means pinning the frame's y to 0.
_OVERLAY_OFFSETS: dict[Gravity, tuple[str, str]] = {
    Gravity.CENTER: ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    Gravity.TOP: ("(main_w-overlay_w)/2", "0"),
    Gravity.BOTTOM: ("(main_w-overlay_w)/2", "(main_h-overlay_h)"),
    Gravity.LEFT: ("0", "(main_h-overlay_h)/2"),
    Gravity.RIGHT: ("(main_w-overlay_w)", "(main_h-overlay_h)/2"),
    Gravity.TOP_LEFT: ("0", "0"),
    Gravity.TOP_RIGHT: ("(main_w-overlay_w)", "0"),
    Gravity.BOTTOM_LEFT: ("0", "(main_h-overlay_h)"),
    Gravity.BOTTOM_RIGHT: ("(main_w-overlay_w)", "(main_h-overlay_h)"),
}


class GifResizerError(RuntimeError):
    """Raised when ffmpeg is missing or fails to process a GIF."""


class GifResizer:
    """Wraps ffmpeg to scale and crop animated GIFs to an exact size."""

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        if shutil.which(ffmpeg_path) is None:
            raise GifResizerError(
                f"ffmpeg executable '{ffmpeg_path}' not found on PATH. "
                "Install it with `brew install ffmpeg`."
            )

        self.ffmpeg_path = ffmpeg_path

    def resize(
        self,
        input_path: Path,
        output_path: Path,
        width: int,
        height: int,
        fit: FitMode = FitMode.COVER,
        gravity: Gravity = Gravity.CENTER,
        background: str = "black",
        fps: int | None = None,
    ) -> None:
        if not input_path.exists():
            raise GifResizerError(f"Input file not found: {input_path}")

        keep_alpha = background in ("transparent", "none")
        filter_chain = self._build_filter_chain(width, height, fit, gravity, background, fps)
        command = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-vf",
            filter_chain,
            "-loop",
            "0",
        ]

        if not keep_alpha:
            # Without this, the GIF encoder re-introduces the exact problem
            # we just flattened away: it crops each frame to only the
            # changed region and fills the rest via a fresh transparent
            # color index + "leave as is" disposal, which simple/embedded
            # decoders can render incorrectly (see _build_filter_chain).
            command += ["-gifflags", "-offsetting-transdiff"]

        command.append(str(output_path))
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode != 0:
            raise GifResizerError(
                f"ffmpeg failed processing {input_path}:\n{result.stderr.strip()}"
            )

    def _build_filter_chain(
        self,
        width: int,
        height: int,
        fit: FitMode,
        gravity: Gravity,
        background: str,
        fps: int | None,
    ) -> str:
        prefix = f"fps={fps}," if fps is not None else ""
        keep_alpha = background in ("transparent", "none")
        reserve_transparent = 1 if keep_alpha else 0

        if fit is FitMode.CONTAIN:
            scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease"
            x, y = _OVERLAY_OFFSETS[gravity]
            canvas_color = "black@0.0" if keep_alpha else background
            graph = (
                f"{prefix}{scale}[fg];"
                f"color=c={canvas_color}:s={width}x{height}[bg];"
                f"[bg][fg]overlay=x={x}:y={y}:format=auto:shortest=1[flat];"
                "[flat]split[s0][s1]"
            )
        else:
            if fit is FitMode.STRETCH:
                scale = f"scale={width}:{height}"
            else:
                x, y = _CROP_OFFSETS[gravity]
                scale = (
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height}:{x}:{y}"
                )

            if keep_alpha:
                graph = f"{prefix}{scale},split[s0][s1]"
            else:
                # Composite onto a solid backdrop so any transparent pixels
                # already in the source (e.g. a hole in the artwork) get
                # baked into a real color instead of relying on the GIF's
                # transparent-color-index mechanism, which many simple/
                # embedded GIF decoders (LED matrix controllers included)
                # don't honor and instead render as ffmpeg's arbitrary
                # leftover palette color for that index.
                graph = (
                    f"{prefix}{scale}[fg];"
                    f"color=c={background}:s={width}x{height}[bg];"
                    "[bg][fg]overlay=x=0:y=0:format=auto:shortest=1[flat];"
                    "[flat]split[s0][s1]"
                )

        return (
            f"{graph};"
            f"[s0]palettegen=stats_mode=full:reserve_transparent={reserve_transparent}[p];"
            "[s1][p]paletteuse=dither=bayer:alpha_threshold=128"
        )
