from __future__ import annotations

from typing import Iterable

from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.text import Text

PRIMARY = "deep_sky_blue1"
SECONDARY = "cyan"
ACCENT = "bright_cyan"
SURFACE = "grey11"
MUTED = "grey70"
SUCCESS = "turquoise2"
WARN = "sky_blue1"
ERROR = "red"
BOX = box.ROUNDED
BOX_SOFT = box.SQUARE


def blue_panel(
    renderable,
    *,
    title: str | Text | None = None,
    subtitle: str | Text | None = None,
    border_style: str = PRIMARY,
    box_style=BOX,
    style: str = f"white on {SURFACE}",
    padding: tuple[int, int] = (1, 2),
):
    if title is not None and subtitle is not None:
        title_text = Text()
        if isinstance(title, Text):
            title_text.append_text(title)
        else:
            title_text.append(str(title), style=f"bold {border_style}")
        title_text.append("  ")
        if isinstance(subtitle, Text):
            title_text.append_text(subtitle)
        else:
            title_text.append(str(subtitle), style=f"dim {MUTED}")
        title = title_text
    return Panel(
        renderable,
        title=title,
        border_style=border_style,
        box=box_style,
        padding=padding,
        style=style,
    )


def section_title(label: str, detail: str | None = None) -> Text:
    title = Text()
    title.append(label, style=f"bold {PRIMARY}")
    if detail:
        title.append("  ")
        title.append(detail, style=f"dim {MUTED}")
    return title


def status_strip(items: Iterable[tuple[str, str, str]]) -> Text:
    strip = Text()
    for index, (label, value, style) in enumerate(items):
        if index:
            strip.append("  ·  ", style=f"dim {MUTED}")
        strip.append(f"{label}: ", style=f"bold {SECONDARY}")
        strip.append(value, style=style)
    return strip


def callout(text: str, *, accent: str = ACCENT) -> Panel:
    body = Align.center(Text(text, style=f"bold {accent}"), vertical="middle")
    return blue_panel(body, border_style=PRIMARY, box_style=BOX, padding=(1, 2))
