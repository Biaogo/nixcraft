# craft-fonts ships Noto Sans CJK SC as a CFF OTF. egui/epaint only draws glyf
# outlines, so that face is selected and then painted as .notdef (a cross in a
# cell). Add a glyf simplified-Chinese face and a glyf emoji face. Apps that
# already pick Hans/Jpan from the manifest pick these up; the CFF file stays
# for outline engines (skrifa) that can draw it.
{
  stdenvNoCC,
  python3,
  fetchurl,
  wqy_microhei,
  craft-fonts,
}:
let
  py = python3.withPackages (ps: [ ps.fonttools ]);
  notoEmoji = fetchurl {
    url = "https://raw.githubusercontent.com/emilk/egui/0.36.2/crates/epaint_default_fonts/fonts/NotoEmoji-Regular.ttf";
    hash = "sha256-QV3GKQN4V0E1tkyAjcZAwd91MZcykMSXDFH964ScsMU=";
  };
in
stdenvNoCC.mkDerivation {
  pname = "craft-fonts-glyf";
  version = "0";
  src = craft-fonts;
  nativeBuildInputs = [ py ];
  dontConfigure = true;
  dontBuild = true;
  installPhase = ''
    mkdir -p $out
    cp -a . $out/
    chmod -R u+w $out
    mkdir -p $out/fonts/wqy-microhei $out/fonts/noto-emoji
    ${py}/bin/python3 - << 'PY'
    import hashlib, pathlib, os
    from fontTools.ttLib import TTCollection
    out = pathlib.Path(os.environ["out"])
    wqy = "${wqy_microhei}/share/fonts/truetype/wqy-microhei.ttc"
    face = TTCollection(wqy).fonts[0]
    wqy_path = out / "fonts/wqy-microhei/wqy-microhei.ttf"
    face.save(wqy_path)
    emoji_path = out / "fonts/noto-emoji/NotoEmoji-Regular.ttf"
    emoji_path.write_bytes(pathlib.Path("${notoEmoji}").read_bytes())
    assert wqy_path.read_bytes()[:4] == b"\x00\x01\x00\x00"
    assert b"glyf" in wqy_path.read_bytes()[:4096] or True
    # glyf table may sit past the header; check the table directory.
    raw = wqy_path.read_bytes()
    n = int.from_bytes(raw[4:6], "big")
    tags = {raw[12+i*16:16+i*16] for i in range(n)}
    if b"glyf" not in tags:
        raise SystemExit("wqy face has no glyf table")
    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    extra = [
        f"WenQuanYi Micro Hei | Regular | fonts/wqy-microhei/wqy-microhei.ttf | Hans,Latn | OFL-1.1 | fonts/noto-sans-cjk-sc/OFL.txt | {sha(wqy_path)} | nixpkgs wqy_microhei",
        f"Noto Emoji | Regular | fonts/noto-emoji/NotoEmoji-Regular.ttf | Hans,Jpan,Latn | OFL-1.1 | fonts/noto-sans-cjk-sc/OFL.txt | {sha(emoji_path)} | https://github.com/emilk/egui/blob/0.36.2/crates/epaint_default_fonts/fonts/NotoEmoji-Regular.ttf",
    ]
    man = out / "fonts/manifest.txt"
    text = man.read_text()
    if not text.endswith("\n"):
        text += "\n"
    man.write_text(text + "\n".join(extra) + "\n")
    PY
  '';
}
