#!/usr/bin/env python3
"""NixOS fixes applied to a Craft app source tree before cargo build.

Fonts live in the nix store and are listed by fontconfig (/etc/fonts/conf.d),
not under /usr/share/fonts. Apps that only scan the FHS paths never see
Noto Sans CJK, so Chinese is missing (spaces or boxes).

DeckCraft / DesignCraft canvas editors only handle Event::Text. fcitx5 commits
arrive as Event::Ime, and the caret never publishes an IME rect, so the
input method never stays up. FilmCraft re-requests focus every frame while a
title on the video is being edited, which drops the candidate window.
"""
import os
import sys

HELPER = r'''
fn nixos_fontconfig_dirs() -> Vec<std::path::PathBuf> {
    // Parents of the files fontconfig already resolved. NixOS keeps those
    // files in the nix store; /usr/share/fonts is empty.
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        use std::os::unix::ffi::OsStringExt;
        let Ok(output) = std::process::Command::new("fc-list").arg("--format=%{file}\n").output() else {
            return Vec::new();
        };
        if !output.status.success() {
            return Vec::new();
        }
        let mut out = Vec::new();
        let mut seen = std::collections::HashSet::new();
        for line in output.stdout.split(|b| *b == b'\n') {
            if line.is_empty() {
                continue;
            }
            let path = std::path::PathBuf::from(std::ffi::OsString::from_vec(line.to_vec()));
            let Some(parent) = path.parent() else { continue };
            if parent.as_os_str().is_empty() || !seen.insert(parent.to_path_buf()) {
                continue;
            }
            out.push(parent.to_path_buf());
        }
        out
    }
    #[cfg(not(all(unix, not(target_os = "macos"))))]
    {
        Vec::new()
    }
}
'''

EXTEND_AFTER = [
    'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts"].map(Into::into));',
    'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts"].map(PathBuf::from));',
    'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/fonts/TTF"].map(Into::into));',
    'let mut dirs = vec![PathBuf::from("/usr/share/fonts"), PathBuf::from("/usr/local/share/fonts")];',
    'v.push("/usr/share/fonts".into());',
    'v.push(PathBuf::from("/usr/share/fonts"));',
]


def walk_rs(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "target", "vendor")]
        for fn in filenames:
            if fn.endswith(".rs"):
                yield os.path.join(dirpath, fn)


def patch_font_dirs(path, text):
    if "nixos_fontconfig_dirs" in text or "/usr/share/fonts" not in text:
        return text, False
    # Test fixtures quote the path as sample data; don't turn those into calls.
    if "example.ttf" in text and "fn system_font_dirs" not in text and "dirs.extend" not in text and "let mut dirs" not in text:
        return text, False
    changed = False
    repls = [
        (
            'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts"].map(Into::into));',
            'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts"].map(Into::into));\n        dirs.extend(nixos_fontconfig_dirs());',
        ),
        (
            'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts"].map(PathBuf::from));',
            'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts"].map(PathBuf::from));\n            dirs.extend(nixos_fontconfig_dirs());',
        ),
        (
            'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/fonts/TTF"].map(Into::into));',
            'dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/fonts/TTF"].map(Into::into));\n            dirs.extend(nixos_fontconfig_dirs());',
        ),
        (
            'let mut dirs = vec![PathBuf::from("/usr/share/fonts"), PathBuf::from("/usr/local/share/fonts")];',
            'let mut dirs = vec![PathBuf::from("/usr/share/fonts"), PathBuf::from("/usr/local/share/fonts")];\n        dirs.extend(nixos_fontconfig_dirs());',
        ),
        (
            'v.push("/usr/share/fonts".into());',
            'v.push("/usr/share/fonts".into());\n        v.extend(nixos_fontconfig_dirs());',
        ),
        (
            'v.push(PathBuf::from("/usr/share/fonts"));',
            'v.push(PathBuf::from("/usr/share/fonts"));\n        v.extend(nixos_fontconfig_dirs());',
        ),
    ]
    for old, new in repls:
        if old in text:
            text = text.replace(old, new, 1)
            changed = True
    if changed:
        text = text.rstrip() + "\n" + HELPER
    return text, changed


def patch_gridcraft(path, text):
    if "fn cjk_han_simplified" not in text or "nixos_fontconfig_dirs" in text:
        return text, False
    old = '''    for d in LINUX_CJK_DIRS {
        v.push((format!("{d}/NotoSansCJKsc-Regular.otf"), 0));
        v.push((format!("{d}/NotoSansCJK-Regular.ttc"), 2)); // SC face
    }'''
    new = old + '''
    for root in nixos_fontconfig_dirs() {
        let ttc = root.join("share/fonts/opentype/noto-cjk/NotoSansCJK-Regular.ttc");
        let flat = root.join("NotoSansCJK-Regular.ttc");
        let nested = root.join("opentype/noto-cjk/NotoSansCJK-Regular.ttc");
        for p in [ttc, nested, flat] {
            if p.is_file() {
                v.push((p.display().to_string(), 2)); // SC face in the region-merged TTC
            }
        }
    }'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1).rstrip() + "\n" + HELPER, True


def patch_cad_cjk(path, text):
    if "pub fn cjk_font()" not in text or "nixos_fontconfig_dirs" in text:
        return text, False
    old = '''                candidates.iter().map(std::path::PathBuf::from).find(|p| p.is_file())'''
    new = '''                candidates.iter().map(std::path::PathBuf::from).find(|p| p.is_file()).or_else(|| {
                    nixos_fontconfig_dirs().into_iter().find_map(|root| {
                        for rel in ["share/fonts/opentype/noto-cjk/NotoSansCJK-Regular.ttc", "opentype/noto-cjk/NotoSansCJK-Regular.ttc", "NotoSansCJK-Regular.ttc"] {
                            let p = root.join(rel);
                            if p.is_file() {
                                return Some(p);
                            }
                        }
                        None
                    })
                })'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1).rstrip() + "\n" + HELPER, True


def patch_pdf_han(path, text):
    if "fn han_candidates" not in text or "nixos_fontconfig_dirs" in text:
        return text, False
    old = '''        unix_fonts(&[
            "truetype/wqy/wqy-microhei.ttc",'''
    new = '''        {
            let mut v = unix_fonts(&[
            "truetype/wqy/wqy-microhei.ttc",'''
    if old not in text:
        return text, False
    # Close the unix_fonts call and append fontconfig hits. The original ends with `])`.
    # Find the closing of this unix_fonts call: the next `])` after old.
    idx = text.find(old)
    end = text.find("])", idx)
    if end < 0:
        return text, False
    end = end + 2
    mid = text[idx + len(old):end]
    if not mid.endswith("])"):
        return text, False
    mid = mid[:-2] + "]);"
    text = text[:idx] + new + mid + '''
            if let Some(p) = nixos_fontconfig_dirs().into_iter().find_map(|root| {
                let p = root.join("NotoSansCJK-Regular.ttc");
                p.is_file().then_some(p)
            }) {
                v.push(p);
            }
            v
        }''' + text[end:]
    return text.rstrip() + "\n" + HELPER, True


def patch_pdf_discover(path, text):
    if "fn font_extension" not in text or "installed_directories" not in text:
        return text, False
    changed = False
    old = 'e.eq_ignore_ascii_case("ttf") || e.eq_ignore_ascii_case("otf")'
    new = 'e.eq_ignore_ascii_case("ttf") || e.eq_ignore_ascii_case("otf") || e.eq_ignore_ascii_case("ttc") || e.eq_ignore_ascii_case("otc")'
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    # Noto CJK TTC is ~19 MiB; the discover cap dropped it.
    old = "meta.is_file() && meta.len() <= (16 << 20) && font_extension(&path)"
    new = "meta.is_file() && meta.len() <= (32 << 20) && font_extension(&path)"
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    old = "f.take((16 << 20) + 1)"
    new = "f.take((32 << 20) + 1)"
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    return text, changed


def patch_soundcraft(path, text):
    if "fn load_from_fontconfig" not in text or "load_cjk_fallback" in text:
        return text, False
    old = '''    fonts.families.insert(FontFamily::Name("bold".into()), bold_family);
    fonts
}'''
    new = '''    fonts.families.insert(FontFamily::Name("bold".into()), bold_family);
    if let Some(cjk) = load_cjk_fallback() {
        fonts.font_data.insert("cjk".into(), Arc::new(cjk));
        for fam in [FontFamily::Proportional, FontFamily::Monospace, FontFamily::Name("bold".into())] {
            if let Some(v) = fonts.families.get_mut(&fam) {
                v.push("cjk".into());
            }
        }
    }
    fonts
}

/// Sans-serif fc-match is DejaVu on this desktop. It has no Han, so Chinese is the .notdef box
/// unless a CJK face is also in the family. egui 0.36 draws CFF via skrifa, so the system
/// Noto CJK TTC is usable. Index from fontconfig (SC is face 2 in the region-merged file).
#[cfg(any(target_os = "linux", target_os = "freebsd"))]
fn load_cjk_fallback() -> Option<FontData> {
    let output = std::process::Command::new("fc-match").args(["--format=%{file}\\n%{index}\\n", "Noto Sans CJK SC"]).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8(output.stdout).ok()?;
    let mut lines = stdout.lines();
    let path = lines.next()?.trim();
    let index = lines.next()?.trim().parse::<u32>().ok()? & 0xFFFF;
    let bytes = std::fs::read(path).ok()?;
    if !matches!(bytes.get(..4), Some(b"\\0\\x01\\0\\0" | b"OTTO" | b"true" | b"ttcf")) {
        return None;
    }
    let mut font = FontData::from_owned(bytes);
    font.index = index;
    Some(font)
}

#[cfg(not(any(target_os = "linux", target_os = "freebsd")))]
fn load_cjk_fallback() -> Option<FontData> {
    None
}'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_deck_ime(path, text):
    old = "                egui::Event::Text(t) => {"
    new = "                egui::Event::Text(t) | egui::Event::Ime(egui::ImeEvent::Commit(t)) => {"
    if "fn keyboard" not in text or old not in text or "ImeEvent::Commit" in text:
        return text, False
    text = text.replace(old, new, 1)
    return text, True


def patch_deck_caret(path, text):
    old = '''            if blink && let Some((cx, top, bot)) = l.caret(deckcraft_text::Pos { para: ts.caret.0, ch: ts.caret.1 }) {
                let (p0, p1) = (xf.to_screen(m * Point::new(cx, top)), xf.to_screen(m * Point::new(cx, bot)));
                painter.line_segment([p0, p1], Stroke::new(1.5, t.caret));
            }'''
    new = '''            if let Some((cx, top, bot)) = l.caret(deckcraft_text::Pos { para: ts.caret.0, ch: ts.caret.1 }) {
                let (p0, p1) = (xf.to_screen(m * Point::new(cx, top)), xf.to_screen(m * Point::new(cx, bot)));
                if blink {
                    painter.line_segment([p0, p1], Stroke::new(1.5, t.caret));
                }
                let cr = egui::Rect::from_two_pos(p0, p1);
                ui.ctx().output_mut(|o| {
                    o.ime = Some(egui::output::IMEOutput {
                        rect: cr,
                        cursor_rect: cr,
                        purpose: Default::default(),
                        should_interrupt_composition: false,
                    });
                });
            }'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_design_ime(path, text):
    old = '''            egui::Event::Text(t) if wants_text => {
                let _ = app.run("text.insert", json!({"text": t}));
            }'''
    new = '''            egui::Event::Text(t) | egui::Event::Ime(egui::ImeEvent::Commit(t)) if wants_text => {
                let _ = app.run("text.insert", json!({"text": t}));
            }'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_design_caret(path, text):
    old = '''        let blink = (painter.ctx().input(|i| i.time) * 1.6) as i64 % 2 == 0;
        if blink {
            let p0 = xf.to_screen(m * Point::new(x, bl - asc));
            let p1 = xf.to_screen(m * Point::new(x, bl + desc));
            painter.line_segment([p0, p1], Stroke::new(1.0, Color32::BLACK));
        }
        painter.ctx().request_repaint_after(std::time::Duration::from_millis(330));'''
    new = '''        let blink = (painter.ctx().input(|i| i.time) * 1.6) as i64 % 2 == 0;
        let p0 = xf.to_screen(m * Point::new(x, bl - asc));
        let p1 = xf.to_screen(m * Point::new(x, bl + desc));
        if blink {
            painter.line_segment([p0, p1], Stroke::new(1.0, Color32::BLACK));
        }
        let cr = egui::Rect::from_two_pos(p0, p1);
        painter.ctx().output_mut(|o| {
            o.ime = Some(egui::output::IMEOutput {
                rect: cr,
                cursor_rect: cr,
                purpose: Default::default(),
                should_interrupt_composition: false,
            });
        });
        painter.ctx().request_repaint_after(std::time::Duration::from_millis(330));'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_film_focus(path, text):
    old = '''    ui.memory_mut(|m| {
        m.request_focus(eid);
        m.set_focus_lock_filter(eid, egui::EventFilter { tab: true, horizontal_arrows: true, vertical_arrows: true, escape: true });
    });'''
    new = '''    ui.memory_mut(|m| {
        // request_focus every frame resets the focus lock and dismisses fcitx on the video frame.
        if m.focused() != Some(eid) {
            m.request_focus(eid);
            m.set_focus_lock_filter(eid, egui::EventFilter { tab: true, horizontal_arrows: true, vertical_arrows: true, escape: true });
        }
    });'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_skip_cff_in_egui(path, text):
    """epaint draws glyf only. A CFF face in the egui stack is selected, then painted as .notdef."""
    if "FontDefinitions" not in text:
        return text, False
    old = "fonts.font_data.insert(name.into(), Arc::new(FontData::from_static(data)));"
    new = """if data.starts_with(b\"OTTO\") { return; }\n        fonts.font_data.insert(name.into(), Arc::new(FontData::from_static(data)));"""
    if old not in text or "data.starts_with(b\"OTTO\")" in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_load_hans_craft(path, text):
    """Canvas FontDb only embedded Japanese craft-fonts. Simplified Chinese never entered the fallback."""
    old = "let craft = crate::japanese_document_fonts().into_iter().map(|f| f.bytes);"
    new = "let craft = crate::japanese_document_fonts().into_iter().chain(crate::CRAFT_FONTS.iter().filter(|f| f.scripts.contains(&\"Hans\"))).map(|f| f.bytes);"
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


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


RULES = [
    patch_font_dirs,
    patch_gridcraft,
    patch_cad_cjk,
    patch_pdf_han,
    patch_pdf_discover,
    patch_soundcraft,
    patch_deck_ime,
    patch_deck_caret,
    patch_design_ime,
    patch_design_caret,
    patch_film_focus,
    patch_skip_cff_in_egui,
    patch_load_hans_craft,
    patch_skip_cbdt,
]


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
