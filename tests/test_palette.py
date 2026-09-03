"""Status palette.

The colours and their contrast figures were supplied as a design reference.
Base colours are fills: #F3DB4C as text on white is 1.4:1 and unreadable, so
these tests pin both the values and the text colour used on each fill.
"""
from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text(encoding="utf-8")

RAISIN = "#232222"
WHITE = "#ffffff"


def relative_luminance(value: str) -> float:
    value = value.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    adjusted = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    red, green, blue = adjusted
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    a, b = relative_luminance(first), relative_luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def variable(name: str) -> str:
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", CSS)
    assert match, f"{name} is not defined in app.css"
    return match.group(1).lower()


def test_palette_values_are_the_supplied_ones():
    assert variable("--raisin") == RAISIN
    assert variable("--success") == "#2eca7c"
    assert variable("--warning") == "#f3db4c"
    assert variable("--danger") == "#ca2e51"


def test_no_tints_are_used():
    """Statuses are solid colours only; the tinted variants were dropped."""
    assert "-soft" not in CSS.replace("--accent-soft", "").replace("--border-soft", "")


def test_supplied_contrast_figures_reproduce():
    """The reference card's numbers for the solid colours, exactly."""
    assert round(contrast("#2eca7c", RAISIN), 2) == 7.45
    assert round(contrast("#f3db4c", RAISIN), 2) == 11.37
    assert round(contrast("#ca2e51", WHITE), 2) == 5.22


def test_text_on_every_fill_passes_aaa():
    assert contrast("#2eca7c", RAISIN) >= 7
    assert contrast("#f3db4c", RAISIN) >= 7
    assert contrast("#ca2e51", WHITE) >= 4.5  # AAA for large/bold badge text


def test_text_on_each_fill_is_the_better_of_raisin_and_white():
    """Inversion rule: whichever of raisin/white gives more contrast wins."""
    for base, expected in (
        ("#2eca7c", RAISIN),
        ("#f3db4c", RAISIN),
        ("#ca2e51", WHITE),
        ("#315f9e", WHITE),   # suggested, light scheme
        ("#79a7e8", RAISIN),  # suggested, dark scheme
    ):
        better = max((contrast(base, RAISIN), RAISIN), (contrast(base, WHITE), WHITE))[1]
        assert better == expected, base


def test_every_status_fill_has_a_paired_text_colour():
    """A background without an --on-* colour would inherit page text."""
    # The pair may be on one line or two.
    fills = re.findall(r"background: var\(--(success|warning|danger|suggested)\);\s*color: var\(--on-\1\)", CSS)
    backgrounds = re.findall(r"background: var\(--(success|warning|danger|suggested)\)", CSS)
    assert len(fills) == len(backgrounds), "a status fill is missing its --on-* text colour"


def test_base_colours_are_never_used_as_text_on_a_light_background():
    """The failure mode the reference card warns about.

    #F3DB4C as a text colour is 1.4:1 on white. Badges must set it as a
    background with a passing text colour, never as `color:`.
    """
    for base in ("--warning", "--success", "--danger"):
        # (?<![-a-z]) so that border-color does not match.
        for match in re.finditer(rf"(?<![-a-z])color:\s*var\({base}\)", CSS):
            snippet = CSS[max(0, match.start() - 200):match.start()]
            assert "background" in snippet, f"{base} used as text colour near: {snippet[-120:]}"


def test_badges_use_a_deliberate_text_colour():
    for name in ("--on-success", "--on-warning", "--on-danger", "--on-suggested"):
        assert f"{name}:" in CSS, name
        assert f"var({name})" in CSS, name
