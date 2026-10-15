"""Font discovery and CJK faces.

Fonts live in the nix store and are listed by fontconfig (/etc/fonts/conf.d), not under
/usr/share/fonts. Apps that only scan the FHS paths never see Noto Sans CJK, so Chinese is
missing (spaces or boxes); a face with no Han gives boxes, a face that is never found gives
spaces, and they are different bugs.
"""


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


def patch_fc_match_charset(path, text):
    """fc-match :lang=zh-cn hits Symbols Nerd Font when that family is prepended. Require a Han probe."""
    old = '&format!(":lang={language}")'
    new = '&format!(":lang={language}:charset={}", match language { "zh-cn" => "73b0", "zh-tw" => "9ad4", "ko" => "ac00", _ => "3042" })'
    if old not in text or "charset=" in text:
        return text, False
    return text.replace(old, new), True
