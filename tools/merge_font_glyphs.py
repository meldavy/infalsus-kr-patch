#!/usr/bin/env python3
"""Add glyphs missing from the patched Nanum fonts using local game fonts.

Run ``ifalsus.py extract-fonts`` first.  This script reads only fonts extracted
from the user's own game installation and writes generated fonts under work/;
no derived game font is committed or distributed by the repository.
"""

import argparse
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont


def merge_missing_glyphs(base_path: Path, fallback_path: Path, output_path: Path):
    base = TTFont(base_path)
    fallback = TTFont(fallback_path)
    base_cmap = base.getBestCmap() or {}
    fallback_cmap = fallback.getBestCmap() or {}
    missing = sorted(set(fallback_cmap) - set(base_cmap))
    fallback_glyphs = fallback.getGlyphSet()
    scale = base["head"].unitsPerEm / fallback["head"].unitsPerEm
    used_names = set(base.getGlyphOrder())
    added = {}

    for codepoint in missing:
        source_name = fallback_cmap[codepoint]
        new_name = f"fallback{codepoint:04X}"
        suffix = 1
        while new_name in used_names:
            suffix += 1
            new_name = f"fallback{codepoint:04X}.{suffix}"

        # Decompose fallback composites so the generated glyph does not retain
        # references to glyph names that only exist in the fallback font.
        recording = DecomposingRecordingPen(fallback_glyphs)
        fallback_glyphs[source_name].draw(recording)
        pen = TTGlyphPen(None)
        recording.replay(TransformPen(pen, (scale, 0, 0, scale, 0, 0)))

        base["glyf"][new_name] = pen.glyph()
        advance, lsb = fallback["hmtx"].metrics[source_name]
        base["hmtx"].metrics[new_name] = (
            round(advance * scale),
            round(lsb * scale),
        )
        used_names.add(new_name)
        added[codepoint] = new_name

    base.setGlyphOrder(base["glyf"].glyphOrder)
    for table in base["cmap"].tables:
        if not table.isUnicode():
            continue
        for codepoint, glyph_name in added.items():
            if table.format in (4, 6) and codepoint > 0xFFFF:
                continue
            table.cmap[codepoint] = glyph_name

    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(output_path)
    return len(added)


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fallback-regular", type=Path,
                        default=repo / "work/fonts/vivoSans-Regular.ttf")
    parser.add_argument("--fallback-bold", type=Path,
                        default=repo / "work/fonts/vivoSans-DemiBold.ttf")
    parser.add_argument("--output-dir", type=Path,
                        default=repo / "work/merged_fonts")
    args = parser.parse_args()

    jobs = (
        ("NanumLatin-Regular.ttf", repo / "fonts/NanumBarunGothic.ttf", args.fallback_regular),
        ("NanumLatin-Bold.ttf", repo / "fonts/NanumBarunGothicBold.ttf", args.fallback_bold),
        ("NanumLatin-Light.ttf", repo / "fonts/NanumBarunGothicLight.ttf", args.fallback_regular),
    )
    for output_name, base, fallback in jobs:
        if not base.is_file():
            parser.error(f"base font not found: {base}")
        if not fallback.is_file():
            parser.error(f"fallback font not found: {fallback}; run extract-fonts first")
        count = merge_missing_glyphs(base, fallback, args.output_dir / output_name)
        print(f"{output_name}: added {count} missing glyphs")


if __name__ == "__main__":
    main()
