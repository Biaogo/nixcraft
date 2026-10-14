# Shared builder for storytold *Craft desktop apps.
# Layout: cargo workspace, GUI at apps/<name>, CLI/MCP at apps/<name>-cli,
# and FreeDesktop files under packaging/linux/. Inspired by lightcraft's nix/package.nix.
{
  lib,
  stdenv,
  rustPlatform,
  pkg-config,
  makeWrapper,
  wayland,
  wayland-scanner,
  libxkbcommon,
  libx11,
  libxcb,
  libxcursor,
  libxi,
  libxrandr,
  vulkan-loader,
  libglvnd,
  dbus,
  alsa-lib,
  fontconfig,
  openssl,
  autoAddDriverRunpath ? null,
  craft-fonts ? null,
}:

{
  pname,
  src,
  binaries ? [
    pname
    "${pname}-cli"
  ],
  appId ? "ai.storyteller.${pname}",
  description,
  homepage ? "https://github.com/storytold/${pname}",
  extraBuildInputs ? [ ],
  extraNativeBuildInputs ? [ ],
  extraAttrs ? { },
}:

let
  version = (builtins.fromTOML (builtins.readFile "${src}/Cargo.toml")).workspace.package.version;
  runtimeLibs = [
    libxkbcommon
    wayland
    libx11
    libxcb
    libxcursor
    libxi
    libxrandr
    vulkan-loader
    libglvnd
    dbus
    alsa-lib
  ];
in
rustPlatform.buildRustPackage (
  {
    inherit pname version src;

    cargoLock = {
      lockFile = "${src}/Cargo.lock";
      allowBuiltinFetchGit = true;
    };

    cargoBuildFlags = [
      "--locked"
    ]
    ++ lib.concatMap (b: [
      "-p"
      b
    ]) binaries;

    # Upstream tests are large and some need a GPU or corpora; skip by default.
    doCheck = false;
    strictDeps = true;

    nativeBuildInputs = [
      pkg-config
      makeWrapper
      wayland-scanner
    ]
    ++ lib.optional (autoAddDriverRunpath != null) autoAddDriverRunpath
    ++ extraNativeBuildInputs;

    buildInputs = [
      wayland
      libxkbcommon
      libx11
      libxcb
      libxcursor
      libxi
      libxrandr
      alsa-lib
      fontconfig
      openssl
      dbus
    ]
    ++ extraBuildInputs;

    env = lib.optionalAttrs (craft-fonts != null) { CRAFT_FONTS_DIR = toString craft-fonts; };

    postInstall = ''
      p=packaging/linux
      if [ -f $p/${appId}.desktop ]; then
        install -Dm644 $p/${appId}.desktop $out/share/applications/${appId}.desktop
      fi
      if [ -f $p/${appId}.mime.xml ]; then
        install -Dm644 $p/${appId}.mime.xml $out/share/mime/packages/${appId}.xml
      fi
      if [ -d assets/app-icon/hicolor ]; then
        mkdir -p $out/share/icons && cp -r assets/app-icon/hicolor $out/share/icons/
      fi
      if [ -f $p/${appId}.metainfo.xml.in ]; then
        install -d $out/share/metainfo
        substitute $p/${appId}.metainfo.xml.in $out/share/metainfo/${appId}.metainfo.xml \
          --subst-var-by VERSION ${version} --subst-var-by DATE 1970-01-01
      fi
      install -Dm644 -t $out/share/doc/${pname} README.md $(ls LICENSE-* NOTICE 2>/dev/null) || true
      for b in $out/bin/*; do
        wrapProgram "$b" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath runtimeLibs}"
      done
    '';

    passthru = { inherit runtimeLibs; };

    meta = {
      inherit description homepage;
      license = with lib.licenses; [
        mit
        asl20
      ];
      platforms = lib.platforms.linux;
      mainProgram = builtins.head binaries;
    };
  }
  // extraAttrs
)
