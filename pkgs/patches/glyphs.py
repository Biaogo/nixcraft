"""Glyphs: the emoji face, and the faces egui or the canvas must not pick.

egui's bundled Noto Emoji has no U+1F9D2, colour emoji (CBDT) has no outline for skrifa to
draw, and epaint cannot paint a CFF face at all. Each of those reads as "the emoji does not
show" or as a cross-in-a-cell, and each needs its own fix.
"""

import os
import re
import sys


def emoji_ttf():
    if len(sys.argv) > 2 and sys.argv[2]:
        return sys.argv[2]
    return os.environ.get("NIXOS_EMOJI_TTF") or ""


def is_test_code(path, text, pos):
    """True when `pos` sits inside test code - those files keep working code untouched."""
    parts = path.replace("\\", "/").split("/")
    if "tests" in parts or path.endswith("_tests.rs"):
        return True
    marker = text.rfind("\n#[cfg(test)]")
    return marker != -1 and pos > marker


def patch_egui_child_emoji(path, text):
    """egui's bundled Noto Emoji has U+1F632 and not U+1F9D2. Append a glyf face that has it."""
    ttf = emoji_ttf()
    if not ttf or "nixos-emoji" in text:
        return text, False
    original = text
    rust_path = ttf.replace("\\", "\\\\").replace('"', '\\"')
    bytes_expr = f'include_bytes!("{rust_path}")'
    changed = False
    for old in (
        "let mut fonts = FontDefinitions::default();",
        "let mut fonts = egui::FontDefinitions::default();",
    ):
        pos = text.find(old)
        if pos == -1 or is_test_code(path, text, pos):
            continue
        insert = (
            old + "\n"
            f'    fonts.font_data.insert("nixos-emoji".into(), std::sync::Arc::new(egui::FontData::from_static({bytes_expr})));\n'
            '    for stack in fonts.families.values_mut() { stack.push("nixos-emoji".into()); }'
        )
        text = text.replace(old, insert, 1)
        changed = True
        break
    needle = '("emoji-icon-font", EMOJI_ICON.as_slice(), 0.90),'
    if needle in text and "nixos-emoji" not in text:
        needle_pos = text.find(needle)
        declarations = list(
            re.finditer(r"\[\(&str, &'static \[u8\], f32\); (\d+)\]", text[:needle_pos])
        )
        if not declarations:
            return original, False
        declaration = declarations[-1]
        bumped = f"[(&str, &'static [u8], f32); {int(declaration.group(1)) + 1}]"
        text = text[:declaration.start()] + bumped + text[declaration.end():]
        text = text.replace(needle, needle + f'\n        ("nixos-emoji", {bytes_expr}, 0.81),', 1)
        text = text.replace(
            'stack(&["Ubuntu-Light", "NotoEmoji-Regular", "emoji-icon-font"])',
            'stack(&["Ubuntu-Light", "NotoEmoji-Regular", "emoji-icon-font", "nixos-emoji"])',
            1,
        )
        text = text.replace(
            'stack(&["Hack", "Ubuntu-Light", "NotoEmoji-Regular", "emoji-icon-font"])',
            'stack(&["Hack", "Ubuntu-Light", "NotoEmoji-Regular", "emoji-icon-font", "nixos-emoji"])',
            1,
        )
        changed = True
    return text, changed


def patch_fig_emoji_fallback(path, text):
    """Without these monochrome faces, U+1F9D2 stays the canvas's missing-glyph box."""
    families = ('"Noto Emoji"', '"WenQuanYi Micro Hei"')
    changed = False

    fallbacks = re.finditer(
        r"const FALLBACK_FAMILIES: \[&str; (\d+)\] = \[(.*?)\];",
        text,
        re.S,
    )
    for fallback in fallbacks:
        body = fallback.group(2)
        needle = '    "Noto Sans Arabic"'
        if '"Noto Sans Arabic"' not in body:
            continue
        if '"Noto Emoji"' not in body and needle in body:
            inserted = (
                '    "Noto Emoji",\n'
                '    "WenQuanYi Micro Hei",\n'
                + needle
            )
            body = body.replace(needle, inserted, 1)
            declaration = (
                f"const FALLBACK_FAMILIES: [&str; {int(fallback.group(1)) + len(families)}] = ["
                f"{body}];"
            )
            text = text[:fallback.start()] + declaration + text[fallback.end():]
            changed = True
        break

    built_ins = re.finditer(
        r"const BUILT_IN: \[&str; (\d+)\] = \[(.*?)\];",
        text,
        re.S,
    )
    for built_in in built_ins:
        body = built_in.group(2)
        if '"BIZ UDPGothic"' not in body:
            continue
        if '"Noto Emoji"' not in body:
            separator = " " if body.endswith(",") else ", "
            declaration = (
                f"const BUILT_IN: [&str; {int(built_in.group(1)) + len(families)}] = ["
                f'{body}{separator}{", ".join(families)}];'
            )
            text = text[:built_in.start()] + declaration + text[built_in.end():]
            changed = True
        break

    return text, changed


def patch_skip_cff_in_egui(path, text):
    """Drop CFF faces before they are named. Returning from add() left the name in the family and epaint panicked."""
    if "FontDefinitions" not in text:
        return text, False
    old = ".filter(|f| f.scripts.contains(&script)).collect()"
    new = '.filter(|f| f.scripts.contains(&script) && !f.bytes.starts_with(b"OTTO")).collect()'
    if old not in text or 'starts_with(b"OTTO")' in text:
        return text, False
    return text.replace(old, new), True


def patch_skip_cbdt(path, text):
    old = "pub fn covers(&self, c: char) -> bool {"
    if old not in text or "face_has_outline" in text or "fn data(&self)" not in text:
        return text, False
    text = text.replace(
        old,
        old + "\n        if !face_has_outline(self.data()) {\n            return false;\n        }",
        1,
    )
    return text.rstrip() + "\n" + OUTLINE_HELPER, True


OUTLINE_HELPER = '''
fn face_has_outline(data: &[u8]) -> bool {
    // CBDT/CBLC colour emoji has a cmap and no outlines. covers() must be false
    // or the outline renderer locks onto it and draws .notdef.
    fn tables(dir: &[u8]) -> bool {
        if dir.len() < 12 { return false; }
        let n = u16::from_be_bytes([dir[4], dir[5]]) as usize;
        let end = 12 + n * 16;
        if dir.len() < end { return false; }
        for i in 0..n {
            let tag = &dir[12 + i * 16..16 + i * 16];
            if tag == b"glyf" || tag == b"CFF " || tag == b"CFF2" { return true; }
        }
        false
    }
    if data.len() < 12 { return false; }
    if &data[..4] == b"ttcf" {
        let n = u32::from_be_bytes(data[8..12].try_into().unwrap_or([0, 0, 0, 0])) as usize;
        if data.len() < 12 + n * 4 { return false; }
        for i in 0..n {
            let off = u32::from_be_bytes(data[12 + i * 4..16 + i * 4].try_into().unwrap_or([0, 0, 0, 0])) as usize;
            if data.get(off..).is_some_and(tables) { return true; }
        }
        return false;
    }
    tables(data)
}
'''


def patch_photocraft_canvas_emoji(path, text):
    """PhotoCraft's canvas only embedded the Japanese craft faces.

    U+1F9D2 then fell through to `Noto Color Emoji`, whose CBDT glyphs have no
    outline: skrifa returns None and the canvas draws nothing. Embed the glyf
    craft emoji face and try it ahead of the colour-emoji families.
    """
    if "craft_fonts" not in text:
        return text, False
    changed = False
    old = "    /// True for a Mincho (serif) face."
    if old in text and "fn is_emoji" not in text:
        text = text.replace(
            old,
            "    /// True for the craft emoji face (the manifest tags it `Zyyy`).\n"
            "    pub fn is_emoji(&self) -> bool {\n"
            '        self.scripts.contains(&"Zyyy")\n'
            "    }\n\n" + old,
            1,
        )
        changed = True
    old = "        for f in crate::craft_fonts::CRAFT_FONTS.iter().filter(|f| f.is_japanese()) {"
    new = "        for f in crate::craft_fonts::CRAFT_FONTS.iter().filter(|f| f.is_japanese() || f.is_emoji()) {"
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    old = 'const FALLBACK_LAST: &[&str] = &["Arial Unicode MS", "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji"];'
    new = 'const FALLBACK_LAST: &[&str] = &["Noto Emoji", "Arial Unicode MS", "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji"];'
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    return text, changed
