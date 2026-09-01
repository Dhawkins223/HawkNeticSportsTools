"""Shrink the self-hosted Inter files to what the dashboard actually renders.

Provenance: the two woff2 files under `dashboard_assets/` are subsets of the
Inter variable font (https://github.com/rsms/inter, SIL Open Font License 1.1),
split on the same `unicode-range` boundaries Google Fonts uses so the browser
fetches `latin-ext` only when a glyph needs it.

**The weight axis ran 100-900.** A variable font carries interpolation data
across its whole axis, and the stylesheet only ever asks for 400, 500, 600 and
700. Narrowing the axis keeps every weight the design system uses and drops the
data for the ones it does not: 48KB to 33KB on `latin`, 19KB to 13KB on
`latin-ext`, with the set of renderable characters unchanged.

Character coverage is not touched, and kerning is kept. Dropping `GPOS` too
would take `latin` to about 17KB, but this is a typography-led design and 16KB
is not worth loose letter-spacing on every heading.

Safe to re-run: if a file's axis is already narrowed, it is left alone rather
than instanced twice.

    python3 scripts/optimize_dashboard_fonts.py [--check]

`--check` reports what would change and exits non-zero if anything would, which
is what CI would use to catch a font replaced with an unoptimized one.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ASSETS = Path(__file__).resolve().parent.parent / "src" / "kalshi_research_bot" / "dashboard_assets"

# The heaviest weight the stylesheet asks for is 700; the lightest is 400.
# Keep the @font-face `font-weight` descriptor in app.css in step with this.
WEIGHT_RANGE = (400, 700)

TARGETS = ("inter-latin.woff2", "inter-latin-ext.woff2")

# Coverage is deliberately *not* re-partitioned. The first attempt at this
# script named the Unicode blocks it thought each file held and subset to them;
# the guessed range missed what `latin-ext` actually contains and produced a
# valid 904-byte font mapping zero codepoints. It would have rendered every
# accented name in a fallback face, and nothing about the file would have looked
# wrong. Each file's own cmap is the only honest description of what it covers,
# so it is read back out and preserved exactly.


def axis_range(font: TTFont) -> tuple[float, float] | None:
    if "fvar" not in font:
        return None
    for axis in font["fvar"].axes:
        if axis.axisTag == "wght":
            return (axis.minValue, axis.maxValue)
    return None


def covered_codepoints(font: TTFont) -> set[int]:
    covered: set[int] = set()
    for table in font["cmap"].tables:
        covered |= set(table.cmap)
    return covered


def optimize(path: Path) -> bytes | None:
    """Return the optimized bytes, or None when the file is already optimized."""
    font = TTFont(path)
    if axis_range(font) == WEIGHT_RANGE:
        return None

    keep = covered_codepoints(font)
    options = subset.Options()
    options.notdef_outline = True
    # Layout features stay: `kern` is what keeps headings from looking loose.
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=keep)
    subsetter.subset(font)

    font = instancer.instantiateVariableFont(font, {"wght": WEIGHT_RANGE}, inplace=False)
    buffer = io.BytesIO()
    font.flavor = "woff2"
    font.save(buffer)

    # Never ship a font that lost coverage; an empty one looks fine until a name
    # needs it.
    rebuilt = covered_codepoints(TTFont(io.BytesIO(buffer.getvalue())))
    if rebuilt != keep:
        raise SystemExit(
            f"{path.name}: coverage changed ({len(keep)} -> {len(rebuilt)} codepoints); refusing to write"
        )
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report without writing")
    arguments = parser.parse_args()

    changed = False
    for name in TARGETS:
        path = ASSETS / name
        if not path.exists():
            print(f"  {name}: missing", file=sys.stderr)
            return 2
        before = path.stat().st_size
        optimized = optimize(path)
        if optimized is None:
            print(f"  {name}: already optimized ({before:,} B)")
            continue
        changed = True
        saved = before - len(optimized)
        verb = "would shrink" if arguments.check else "shrank"
        print(f"  {name}: {verb} {before:,} -> {len(optimized):,} B  (-{100 * saved // before}%)")
        if not arguments.check:
            path.write_bytes(optimized)

    if arguments.check and changed:
        print("\nfonts are not optimized; run scripts/optimize_dashboard_fonts.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
