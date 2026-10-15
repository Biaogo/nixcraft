# ArtCraft is Tauri + an npm frontend, not the pure-Rust *Craft layout.
# AUR runs `npx nx run artcraft:build`, then `cargo build --features tauri/custom-protocol`.
# nx's native pty panics in the Nix sandbox, so call vite directly. tauri-build embeds
# frontend/apps/artcraft/dist when the custom-protocol feature is on.
{
  lib,
  stdenv,
  rustPlatform,
  fetchNpmDeps,
  nodejs,
  npmHooks,
  pkg-config,
  wrapGAppsHook3,
  copyDesktopItems,
  makeDesktopItem,
  cargo-tauri,
  cmake,
  perl,
  gitMinimal,
  llvmPackages,
  zlib,
  openssl,
  sqlite,
  dbus,
  alsa-lib,
  gtk3,
  cairo,
  gdk-pixbuf,
  glib,
  glib-networking,
  pango,
  libsoup_3,
  webkitgtk_4_1,
  gst_all_1,
  src,
}:

let
  version =
    (builtins.fromJSON (builtins.readFile "${src}/crates/desktop/artcraft/tauri.conf.json")).version;
  npmDeps = fetchNpmDeps {
    name = "artcraft-${version}-npm-deps";
    src = src + "/frontend";
    # Workspaces need packuments. The lockfile has one git+ssh dep (ccapture.js);
    # prefetch-npm-deps rewrites that to a GitHub tarball.
    fetcherVersion = 2;
    hash = "sha256-MdPy2OlDsZKVE6lcKzUNvPzWAAalKgECWwcQjOyhMNc=";
  };
  gstPlugins = [
    cargo-tauri.gst-plugin
    gst_all_1.gstreamer
    gst_all_1.gst-plugins-base
    gst_all_1.gst-plugins-good
    gst_all_1.gst-plugins-bad
    gst_all_1.gst-libav
  ];
in
rustPlatform.buildRustPackage {
  pname = "artcraft";
  inherit version src npmDeps;

  cargoLock.lockFile = "${src}/Cargo.lock";

  # Frontend lockfile lives in frontend/; npmConfigHook installs there.
  npmRoot = "frontend";
  # Git deps make npm write into the cache during `npm ci`.
  makeCacheWritable = true;

  cargoBuildFlags = [
    "-p"
    "artcraft"
    "--features"
    "tauri/custom-protocol"
  ];

  doCheck = false;
  strictDeps = true;

  nativeBuildInputs = [
    pkg-config
    cmake
    perl
    gitMinimal
    llvmPackages.libclang
    nodejs
    npmHooks.npmConfigHook
    wrapGAppsHook3
    copyDesktopItems
  ];

  buildInputs = [
    openssl
    sqlite
    dbus
    alsa-lib
    gtk3
    cairo
    gdk-pixbuf
    glib
    glib-networking
    pango
    libsoup_3
    webkitgtk_4_1
    zlib
  ]
  ++ gstPlugins;

  env = {
    NIX_NPM_FETCHER_VERSION = "2";
    SQLX_OFFLINE = "true";
    # boring-sys2 (wreq) runs bindgen against BoringSSL.
    LIBCLANG_PATH = "${llvmPackages.libclang.lib}/lib";
    BINDGEN_EXTRA_CLANG_ARGS = "-isystem ${stdenv.cc.libc.dev}/include -isystem ${llvmPackages.libclang.lib}/lib/clang/${lib.versions.major llvmPackages.libclang.version}/include";
    # Upstream release profile is fat LTO; that OOMs. Match the AUR recipe.
    CARGO_PROFILE_RELEASE_LTO = "thin";
    VITE_ENVIRONMENT_TYPE = "production";
    NODE_OPTIONS = "--max-old-space-size=8192";
    NX_DAEMON = "false";
    # nx's native pty panics in the sandbox (vt100 unwrap). The build target is vite.
    CI = "true";
  };

  preBuild = ''
    pushd frontend/apps/artcraft
    node ../../node_modules/vite/bin/vite.js build
    popd
    # tauri-build runs this from the crate dir. Same pty panic, and dist is already built.
    substituteInPlace crates/desktop/artcraft/tauri.conf.json \
      --replace-fail '"beforeBuildCommand": "npx nx run artcraft:build"' '"beforeBuildCommand": "true"'
  '';

  postInstall = ''
    # The crate also emits a staticlib. The GUI binary is the product.
    rm -rf $out/lib
    install -Dm644 crates/desktop/artcraft/icons/32x32.png \
      $out/share/icons/hicolor/32x32/apps/ai.artcraft.app.png
    install -Dm644 crates/desktop/artcraft/icons/128x128.png \
      $out/share/icons/hicolor/128x128/apps/ai.artcraft.app.png
    install -Dm644 crates/desktop/artcraft/icons/128x128@2x.png \
      $out/share/icons/hicolor/256x256/apps/ai.artcraft.app.png
    if [ -f LICENSE.md ]; then
      install -Dm644 LICENSE.md $out/share/licenses/artcraft/LICENSE.md
    fi
  '';

  desktopItems = [
    (makeDesktopItem {
      name = "ai.artcraft.app";
      desktopName = "ArtCraft";
      exec = "artcraft";
      icon = "ai.artcraft.app";
      comment = "IDE for interactive AI image and video creation";
      categories = [
        "Graphics"
        "AudioVideo"
      ];
      startupWMClass = "ArtCraft";
    })
  ];

  preFixup = ''
    gappsWrapperArgs+=(
      --prefix WEBKIT_GST_ALLOWED_URI_PROTOCOLS : "asset"
      --prefix GST_PLUGIN_SYSTEM_PATH_1_0 : "${
        lib.makeSearchPathOutput "lib" "lib/gstreamer-1.0" gstPlugins
      }"
      # NVIDIA + WebKit explicit sync. https://github.com/tauri-apps/tauri/issues/9394
      --set-default __NV_DISABLE_EXPLICIT_SYNC 1
    )
  '';

  passthru = {
    inherit npmDeps;
  };

  meta = {
    description = "IDE for interactive AI image and video creation";
    homepage = "https://getartcraft.com";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "artcraft";
  };
}
