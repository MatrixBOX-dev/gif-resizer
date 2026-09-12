import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from gif_resizer.resizer import FitMode, GifResizer, GifResizerError, Gravity


@pytest.fixture
def sample_gif(tmp_path: Path) -> Path:
    gif_path = tmp_path / "sample.gif"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:duration=1:rate=5",
            str(gif_path),
        ],
        check=True,
        capture_output=True,
    )
    return gif_path


@pytest.fixture
def transparent_gif(tmp_path: Path) -> Path:
    gif_path = tmp_path / "transparent.gif"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                "color=c=red:s=100x60:d=1:r=5,format=rgba,"
                "drawbox=x=30:y=15:w=30:h=30:color=magenta:t=fill,"
                "colorkey=0xff00ff:0.1:0.1,split[s0][s1];"
                "[s0]palettegen=reserve_transparent=1[p];[s1][p]paletteuse=alpha_threshold=128"
            ),
            str(gif_path),
        ],
        check=True,
        capture_output=True,
    )
    return gif_path


def test_resize_cover_produces_exact_size(sample_gif: Path, tmp_path: Path) -> None:
    output_path = tmp_path / "out.gif"
    resizer = GifResizer()

    resizer.resize(sample_gif, output_path, width=128, height=32, fit=FitMode.COVER)

    assert output_path.exists()
    assert _gif_dimensions(output_path) == (128, 32)


def test_resize_contain_produces_exact_size(sample_gif: Path, tmp_path: Path) -> None:
    output_path = tmp_path / "out.gif"
    resizer = GifResizer()

    resizer.resize(
        sample_gif,
        output_path,
        width=192,
        height=32,
        fit=FitMode.CONTAIN,
        gravity=Gravity.TOP,
    )

    assert output_path.exists()
    assert _gif_dimensions(output_path) == (192, 32)


def _alpha_at(image: Image.Image, x: int, y: int) -> int:
    pixel = image.convert("RGBA").getpixel((x, y))
    assert isinstance(pixel, tuple)
    return pixel[3]


def test_cover_default_flattens_interior_transparency_to_black(
    transparent_gif: Path, tmp_path: Path
) -> None:
    output_path = tmp_path / "out.gif"
    resizer = GifResizer()

    resizer.resize(transparent_gif, output_path, width=128, height=32, fit=FitMode.COVER)

    image = Image.open(output_path).convert("RGBA")
    center = image.getpixel((image.width // 2, image.height // 2))
    assert center == (0, 0, 0, 255)


def test_cover_transparent_background_preserves_interior_transparency(
    transparent_gif: Path, tmp_path: Path
) -> None:
    output_path = tmp_path / "out.gif"
    resizer = GifResizer()

    resizer.resize(
        transparent_gif,
        output_path,
        width=128,
        height=32,
        fit=FitMode.COVER,
        background="transparent",
    )

    image = Image.open(output_path)
    assert _alpha_at(image, image.width // 2, image.height // 2) == 0


def test_contain_default_background_is_solid_black(transparent_gif: Path, tmp_path: Path) -> None:
    output_path = tmp_path / "out.gif"
    resizer = GifResizer()

    resizer.resize(transparent_gif, output_path, width=192, height=32, fit=FitMode.CONTAIN)

    image = Image.open(output_path).convert("RGBA")
    assert image.getpixel((1, 1)) == (0, 0, 0, 255)


def test_contain_transparent_background_stays_transparent(
    transparent_gif: Path, tmp_path: Path
) -> None:
    output_path = tmp_path / "out.gif"
    resizer = GifResizer()

    resizer.resize(
        transparent_gif,
        output_path,
        width=192,
        height=32,
        fit=FitMode.CONTAIN,
        background="transparent",
    )

    image = Image.open(output_path)
    assert _alpha_at(image, 1, 1) == 0


def test_contain_default_output_has_no_frame_transparency(
    transparent_gif: Path, tmp_path: Path
) -> None:
    """Regression test: the gif encoder's own frame-diffing (independent of
    our filter graph) re-introduces a transparent color index + "leave as
    is" disposal for unchanged regions unless explicitly disabled, which
    defeats flattening onto a solid background for decoders that don't
    honor GIF transparency.
    """
    if shutil.which("gifsicle") is None:
        pytest.skip("gifsicle not installed")

    output_path = tmp_path / "out.gif"
    resizer = GifResizer()

    resizer.resize(transparent_gif, output_path, width=192, height=32, fit=FitMode.CONTAIN)

    info = subprocess.run(
        ["gifsicle", "--info", str(output_path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "transparent" not in info


def test_resize_missing_input_raises() -> None:
    resizer = GifResizer()

    with pytest.raises(GifResizerError, match="not found"):
        resizer.resize(
            Path("/nonexistent/input.gif"),
            Path("/tmp/out.gif"),
            width=128,
            height=32,
        )


def _gif_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width_str, height_str = result.stdout.strip().split("x")
    return int(width_str), int(height_str)
