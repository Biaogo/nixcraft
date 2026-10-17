"""NixOS fixes applied to a Craft app source tree before cargo build.

Rules live in the sibling modules, one per concern:

  fonts.py    fontconfig discovery and the CJK faces (spaces, boxes, tofu)
  glyphs.py   emoji and the faces egui or the canvas must not pick
  ime.py      fcitx5 commits, the caret rect, focus that re-requests every frame
  ui.py       widgets the app paints by hand

Usage: engine.py <source root> [emoji ttf]

glyphs.emoji_ttf reads the second argument, or NIXOS_EMOJI_TTF. RULES keeps the order the
rules were applied in before the split; every rule returns (text, changed) and no-ops when
its needle is absent, which is what `.github/ci/patch-drift.py` reports on.
"""

import os
import sys

# Loaded by path (the drift checker) as well as run as a script: make the siblings importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fonts, glyphs, ime, ui


def walk_rs(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "target", "vendor")]
        for fn in filenames:
            if fn.endswith(".rs"):
                yield os.path.join(dirpath, fn)


RULES = [
    fonts.patch_font_dirs,
    fonts.patch_gridcraft,
    fonts.patch_cad_cjk,
    fonts.patch_pdf_han,
    fonts.patch_pdf_discover,
    fonts.patch_soundcraft,
    ime.patch_design_ime,
    ime.patch_design_caret,
    ui.patch_design_search,
    ime.patch_film_focus,
    glyphs.patch_skip_cff_in_egui,
    fonts.patch_fc_match_charset,
    glyphs.patch_egui_child_emoji,
    glyphs.patch_fig_emoji_fallback,
    ime.patch_vector_search_ime,
    fonts.patch_load_hans_craft,
    glyphs.patch_skip_cbdt,
    glyphs.patch_photocraft_canvas_emoji,]


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    n = 0
    for path in walk_rs(root):
        text = open(path, encoding="utf-8", errors="surrogateescape").read()
        orig = text
        for rule in RULES:
            text, _ = rule(path, text)
        if text != orig:
            open(path, "w", encoding="utf-8", errors="surrogateescape").write(text)
            print("patched", os.path.relpath(path, root))
            n += 1
    print(f"nixos-fonts: {n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
