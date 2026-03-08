from __future__ import annotations

import time
from typing import Iterable

ORACLE_TITLE = "ORACLE"
ORACLE_QUOTE = (
    "Millionaires study markets, billionaires study the stars"
)

try:  # optional enhancement
    from rich.align import Align  # type: ignore
    from rich.console import Console, Group  # type: ignore
    from rich.live import Live  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.text import Text  # type: ignore
except Exception:  # noqa: BLE001
    Align = None
    Console = None
    Group = None
    Live = None
    Panel = None
    Text = None


def _plain_title() -> str:
    try:
        from pyfiglet import Figlet  # type: ignore

        return Figlet(font="slant").renderText(ORACLE_TITLE).rstrip()
    except Exception:  # noqa: BLE001
        return ORACLE_TITLE


def _plain_render() -> None:
    print()
    print("✦  ✧   ✦    ✧   ✦")
    print(_plain_title())
    print(ORACLE_QUOTE)
    print()


def _rich_frames() -> Iterable[object]:
    assert Panel is not None and Text is not None and Group is not None and Align is not None
    starfields = [
        "✦     ·    ✧      ·     ✦\n   ✧      ✦      ✧\n✦    ·      ✧     ·    ✦",
        "  ✧    ·    ✦      ·    ✧\n✦      ✧      ✦\n   ✦   ·     ✧    ·    ✦",
        "✦   ·     ✧      ·     ✦\n   ✦      ✧      ✦\n✧    ·      ✦     ·    ✧",
    ]
    crystal = [
        "      .-''''-.\n    .'  .--.  '.\n   /   (    )   \\\n  |     '--'     |\n   \\   .--.    /\n    '.(____).'\n      / /\\ \\\n     /_/  \\_\\",
        "      .-''''-.\n    .'  .--.  '.\n   /   ( () )   \\\n  |     '--'     |\n   \\   .--.    /\n    '.(____).'\n      / /\\ \\\n     /_/  \\_\\",
    ]
    colors = ["magenta", "bright_magenta", "cyan", "bright_cyan"]

    for index, stars in enumerate(starfields):
        veil = Text(stars, style=colors[index % len(colors)])
        yield Panel(Align.center(veil), border_style=colors[index % len(colors)], title="✦ starfield veil ✦")

    title = Text(ORACLE_TITLE, style="bold bright_magenta")
    quote = Text(ORACLE_QUOTE, style="italic bright_cyan")
    yield Panel(
        Align.center(Group(title, Text(""), quote)),
        border_style="bright_magenta",
        title="oracle awakens",
    )

    for index, ball in enumerate(crystal):
        aura = Text(ball, style=colors[(index + 1) % len(colors)])
        hands = Text("          ⟪     🔮     ⟫", style="bold bright_white")
        yield Panel(
            Align.center(Group(aura, Text(""), hands, Text(""), Text("Who seeks the stars?", style="bold bright_cyan"))),
            border_style=colors[(index + 1) % len(colors)],
            title="crystal ball sequence",
        )


def run_awakening(*, plain: bool = False) -> None:
    if plain or Console is None or Live is None:
        _plain_render()
        return

    console = Console()
    frames = list(_rich_frames())
    with Live(frames[0], console=console, refresh_per_second=12, transient=False) as live:
        for frame in frames:
            live.update(frame)
            time.sleep(0.28)
    console.print()


def main() -> int:
    run_awakening()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
