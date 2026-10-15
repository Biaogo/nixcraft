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
        # Upstream moved the unix branch into `fn unix_font_dirs` (2026-10-15, DesignCraft
        # a930276): the list is built in one `let` with `Into::into`, not `extend`ed.
        (
            'let mut dirs: Vec<std::path::PathBuf> = ["/usr/share/fonts", "/usr/local/share/fonts"].map(Into::into).into();',
            'let mut dirs: Vec<std::path::PathBuf> = ["/usr/share/fonts", "/usr/local/share/fonts"].map(Into::into).into();\n    dirs.extend(nixos_fontconfig_dirs());',
        ),
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
    if "fn load_from_fontconfig" not in text or "charset=73b0" in text:
        return text, False
    old = '''    if let Some(h) = load(HANGUL, "sans-serif:lang=ko", Some("ko")) {
        fonts.font_data.insert("system-hangul".into(), Arc::new(h));
        for family in fonts.families.values_mut() {
            family.push("system-hangul".into());
        }
    }
    fonts
}'''
    new = '''    if let Some(h) = load(HANGUL, "sans-serif:lang=ko", Some("ko")) {
        fonts.font_data.insert("system-hangul".into(), Arc::new(h));
        for family in fonts.families.values_mut() {
            family.push("system-hangul".into());
        }
    }
    // sans-serif is DejaVu here. It has no Han, so Chinese is a hollow box unless a CJK face is in the family.
    if let Some(han) = load(&[] as &[(&str, u32)], ":lang=zh-cn:charset=73b0", Some("zh-cn")) {
        fonts.font_data.insert("system-han".into(), Arc::new(han));
        for family in fonts.families.values_mut() {
            family.push("system-han".into());
        }
    }
    fonts
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


def patch_design_search(path, text):
    """The app bar's Search field is painted by hand and its response was dropped.

    ``allocate_exact_size`` returns ``(Rect, Response)``; the app kept the Rect for
    painting and bound the Response to ``_``, so a click on the field did nothing.
    Bind it and open Quick Apply, the app's only search UI.
    """
    old = '''                        // Search field.
                        let (r, _) = ui.allocate_exact_size(vec2(125.0, 18.0), Sense::click());'''
    new = '''                        // Search field. The field is painted by hand, so its response is the
                        // only thing that knows it was clicked; it opens Quick Apply (Cmd+Return).
                        let (r, search_resp) = ui.allocate_exact_size(vec2(125.0, 18.0), Sense::click());
                        if search_resp.clicked() {
                            let _ = app.run("app.palette", json!(null));
                        }'''
    if new in text:
        return text, False
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
    """Drop CFF faces before they are named. Returning from add() left the name in the family and epaint panicked."""
    if "FontDefinitions" not in text:
        return text, False
    old = ".filter(|f| f.scripts.contains(&script)).collect()"
    new = '.filter(|f| f.scripts.contains(&script) && !f.bytes.starts_with(b"OTTO")).collect()'
    if old not in text or 'starts_with(b"OTTO")' in text:
        return text, False
    return text.replace(old, new), True


def patch_fc_match_charset(path, text):
    """fc-match :lang=zh-cn hits Symbols Nerd Font when that family is prepended. Require a Han probe."""
    old = '&format!(":lang={language}")'
    new = '&format!(":lang={language}:charset={}", match language { "zh-cn" => "73b0", "zh-tw" => "9ad4", "ko" => "ac00", _ => "3042" })'
    if old not in text or "charset=" in text:
        return text, False
    return text.replace(old, new), True


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
        text = text.replace("[(&str, &'static [u8], f32); 4]", "[(&str, &'static [u8], f32); 5]", 1)
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
    """Canvas fallbacks never name Noto Emoji, so U+1F9D2 stays the missing-glyph box."""
    changed = False
    old = '''            "Apple Color Emoji",
            "Noto Sans Arabic",'''
    new = '''            "Apple Color Emoji",
            "Noto Emoji",
            "WenQuanYi Micro Hei",
            "Noto Sans Arabic",'''
    if old in text and '"Noto Emoji"' not in text:
        text = text.replace(old, new, 1)
        changed = True
    old = 'const BUILT_IN: [&str; 4] = ["Inter", "BIZ UDPGothic", "Noto Sans CJK SC", "Noto Sans Arabic"];'
    new = 'const BUILT_IN: [&str; 6] = ["Inter", "BIZ UDPGothic", "Noto Sans CJK SC", "Noto Sans Arabic", "Noto Emoji", "WenQuanYi Micro Hei"];'
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    return text, changed


def patch_vector_search_ime(path, text):
    """request_focus every frame resets text-input-v3 and fcitx dismisses."""
    changed = False
    old = '''pub fn show(app: &mut VectorcraftApp, ctx: &egui::Context) {
    if !app.ui.palette_open {
        return;
    }'''
    new = '''pub fn show(app: &mut VectorcraftApp, ctx: &egui::Context) {
    if !app.ui.palette_open {
        ctx.data_mut(|d| d.remove::<bool>(egui::Id::new("palette-ime-focus")));
        return;
    }'''
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    old = '''            let r = ui.add(egui::TextEdit::singleline(&mut app.ui.palette_query).hint_text(tl!("Search commands and tools…")).desired_width(500.0));
            r.request_focus();'''
    new = '''            let r = ui.add(egui::TextEdit::singleline(&mut app.ui.palette_query).hint_text(tl!("Search commands and tools…")).desired_width(500.0));
            // Once per open. Every frame dismisses fcitx.
            let ime = egui::Id::new("palette-ime-focus");
            if !ui.data(|d| d.get_temp::<bool>(ime)).unwrap_or(false) {
                r.request_focus();
                ui.data_mut(|d| d.insert_temp(ime, true));
            }'''
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    old = '''    if ui.memory(|m| m.focused().is_none()) {
        ui.memory_mut(|m| m.request_focus(field.with("edit")));
    }'''
    new = '''    // The sizing pass has no widget yet. Focus once on the next frame, not every frame.
    if pass == st.opened + 1 {
        ui.memory_mut(|m| m.request_focus(field.with("edit")));
    }'''
    if old in text and "pass == st.opened + 1" not in text:
        text = text.replace(old, new, 1)
        changed = True
    return text, changed

def patch_load_hans_craft(path, text):
    """Canvas FontDb only embedded Japanese craft-fonts. Simplified Chinese never entered the fallback."""
    old = "let craft = crate::japanese_document_fonts().into_iter().map(|f| f.bytes);"
    new = (
        "let craft = crate::japanese_document_fonts().into_iter().chain(crate::CRAFT_FONTS.iter()"
        '.filter(|f| f.scripts.contains(&"Hans") || f.scripts.contains(&"Zyyy"))).map(|f| f.bytes);'
    )
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


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
    patch_design_search,
    patch_film_focus,
    patch_skip_cff_in_egui,
    patch_fc_match_charset,
    patch_egui_child_emoji,
    patch_fig_emoji_fallback,
    patch_vector_search_ime,
    patch_load_hans_craft,
    patch_skip_cbdt,
    patch_photocraft_canvas_emoji,
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
