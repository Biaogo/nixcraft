# Per-package arguments for mk-craft.nix. `inputs` are flake inputs pinned in flake.lock.
{ inputs }:
{
  photocraft = {
    src = inputs.photocraft-src;
    description = "PhotoCraft — layered image editor";
  };
  pdfcraft = {
    src = inputs.pdfcraft-src;
    description = "PDFCraft — PDF editor";
    # Workaround: rten-gemm 0.26's `_mm512_dpbusd_epi32` fails to compile with
    # nixpkgs rustc 1.98 / LLVM 21 (intrinsic signature mismatch for
    # llvm.x86.avx512.vpdpbusd.512). Use the same instruction via inline asm,
    # matching what rten-gemm already does in kernels/x86_64.rs.
    extraAttrs.preBuild = ''
      v=$(readlink -f "$NIX_BUILD_TOP/cargo-vendor-dir")
      if [ "$v" != "$NIX_BUILD_TOP/cargo-vendor-dir" ]; then
        rm "$NIX_BUILD_TOP/cargo-vendor-dir"; mkdir "$NIX_BUILD_TOP/cargo-vendor-dir"
        cp -rs "$v"/. "$NIX_BUILD_TOP/cargo-vendor-dir"/
      fi
      d="$NIX_BUILD_TOP/cargo-vendor-dir/rten-gemm-0.26.0"
      if [ -L "$d" ]; then t=$(readlink -f "$d"); rm "$d"; cp -rL "$t" "$d"; chmod -R u+w "$d"; fi
      f="$d/src/i8dot.rs"
      if [ -L "$f" ]; then cp --remove-destination "$(readlink -f "$f")" "$f"; fi
      chmod u+w "$f"
      substituteInPlace "$d/src/i8dot.rs" --replace-fail \
        "_mm512_dpbusd_epi32(acc.0, a.0, b.0).into()" \
        "{ let mut c = acc.0; std::arch::asm!(\"vpdpbusd {c}, {a}, {b}\", c = inout(zmm_reg) c, a = in(zmm_reg) a.0, b = in(zmm_reg) b.0, options(nostack)); c.into() }"
    '';
  };
  filmcraft = {
    src = inputs.filmcraft-src;
    description = "FilmCraft — video editor";
  };
  lightcraft = {
    src = inputs.lightcraft-src;
    description = "LightCraft — photo library and raw developer";
  };
  wordcraft = {
    src = inputs.wordcraft-src;
    description = "WordCraft — word processor";
  };
  vectorcraft = {
    src = inputs.vectorcraft-src;
    description = "VectorCraft — vector graphics editor";
  };
  effectcraft = {
    src = inputs.effectcraft-src;
    description = "EffectCraft — motion graphics / effects";
  };
  gridcraft = {
    src = inputs.gridcraft-src;
    description = "GridCraft — spreadsheet";
  };
  cadcraft = {
    src = inputs.cadcraft-src;
    description = "CADCraft — CAD modeller";
  };
  designcraft = {
    src = inputs.designcraft-src;
    description = "DesignCraft — graphic design tool";
  };
  deckcraft = {
    src = inputs.deckcraft-src;
    description = "DeckCraft — presentation editor";
  };
  soundcraft = {
    src = inputs.soundcraft-src;
    description = "SoundCraft — audio editor";
  };
  figcraft = {
    src = inputs.figcraft-src;
    description = "FigCraft — UI/interface design tool";
  };
}
