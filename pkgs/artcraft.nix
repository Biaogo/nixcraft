# ArtCraft is Tauri + an npm/nx frontend, not the pure-Rust *Craft layout.
# AUR builds the frontend first, then `cargo build --features tauri/custom-protocol`
# so tauri-build embeds frontend/apps/artcraft/dist. `cargo tauri build` is worse
# here: beforeBuildCommand runs from the crate dir, where `nx` is not the workspace.
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
    hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
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
  ]
  ++ gstPlugins;

  env = {
    NIX_NPM_FETCHER_VERSION = "2";
    SQLX_OFFLINE = "true";
    # Upstream release profile is fat LTO; that OOMs. Match the AUR recipe.
    CARGO_PROFILE_RELEASE_LTO = "thin";
    VITE_ENVIRONMENT_TYPE = "production";
    NODE_OPTIONS = "--max-old-space-size=8192";
    NX_DAEMON = "false";
  };

  preBuild = ''
    pushd frontend
    npx nx run artcraft:build
    popd
  '';

  postInstall = ''
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
