# nixcraft

Nix flake packaging of the [storytold](https://github.com/storytold) Craft desktop apps. Everything except ArtCraft (Tauri + npm) is pure Rust.

[中文](README.md)

## Packages

| Attribute | Description |
| --- | --- |
| `photocraft` | Layered image editor |
| `pdfcraft` | PDF editor |
| `filmcraft` | Video editor |
| `lightcraft` | Photo library and non-destructive raw developer |
| `wordcraft` | Word processor |
| `vectorcraft` | Vector graphics |
| `effectcraft` | Motion graphics / effects |
| `gridcraft` | Spreadsheet |
| `cadcraft` | CAD modeller |
| `designcraft` | Graphic design |
| `deckcraft` | Presentation editor |
| `soundcraft` | Audio editor |
| `figcraft` | UI / interface design |
| `artcraft` | IDE for interactive AI image and video creation (Tauri + npm frontend, GUI only) |

Except `artcraft`, each package usually ships a GUI binary (`<name>`) and a CLI / MCP binary (`<name>-cli`). `default` / `all` is a symlinkJoin of every package.

Not packaged: `artcraftx`, `craft-launcher`. Web (wasm) builds are also omitted.

Platforms: `x86_64-linux`, `aarch64-linux` (CI currently builds the former only).

## Quick start

```sh
nix run github:Biaogo/nixcraft#photocraft
nix build github:Biaogo/nixcraft#gridcraft
nix build github:Biaogo/nixcraft   # everything
```

## Add to a flake / NixOS

```nix
# flake.nix
inputs.nixcraft = {
  url = "github:Biaogo/nixcraft";
  # Optional: follow your own nixpkgs (needs rustc ≥ 1.95; unstable recommended)
  # inputs.nixpkgs.follows = "nixpkgs";
};

# In a NixOS module (or home-manager / nix-darwin equivalent):
{
  nixpkgs.overlays = [ inputs.nixcraft.overlays.default ];
  environment.systemPackages = with pkgs; [
    photocraft
    lightcraft
    # or: nixcraft-all
  ];
}
```

You can also use `inputs.nixcraft.packages.${system}.photocraft` without an overlay.

## Cachix binary cache

CI pushes **final package outputs** (not build-time dependencies) to the public [biaogo](https://app.cachix.org/cache/biaogo) cache. Add this to your Nix / NixOS config:

```nix
nix.settings = {
  substituters = [ "https://biaogo.cachix.org" ];
  trusted-public-keys = [
    "biaogo.cachix.org-1:pEsKASFTETzWAVGGsjpHnq869V5KNeDOBhQahLlrPzY="
  ];
};
```

The public key comes from the [Cachix API](https://cachix.org/api/v1/cache/biaogo). If you fork this repo and push to the cache, set `CACHIX_AUTH_TOKEN` in GitHub Actions. **A run that already started will not see a secret added mid-flight — start a new run.**

## CI

`.github/workflows/build.yml`:

- **Triggers:** daily at **00:00 Asia/Shanghai**, `workflow_dispatch`, and pushes to `main` (ignores commits that only touch `flake.lock`)
- **`force`:** build and `cachix push` / `pin` even when already on the latest Release; does **not** change per-package lock entries
- **`bump_nixpkgs`:** scheduled runs **always** run `nix flake update nixpkgs`; on `workflow_dispatch` only when checked. A bump rebuilds and pushes every package (like force) and commits the new nixpkgs lock via `commit-lock` (`[skip ci]`). Independent of `force`; both can be enabled together
- **Per package:** fetch the latest GitHub Release of `storytold/<pkg>`; skip if it matches the pin and neither force nor bump is on; otherwise lock to that tag, build, push, and pin
- **Cachix secret:** if a build runs and `CACHIX_AUTH_TOKEN` is missing, the push step **fails**. Cancel and re-dispatch (optionally with force / bump_nixpkgs)
- **Commit-back:** `commit-lock` merges package lock nodes that changed plus the nixpkgs node when bumped, then pushes as github-actions[bot]

## Notes

- `doCheck = false` by default (upstream tests are slow; some need a GPU or corpora)
- Tracks nixos-unstable for a recent rustc; embeds `craft-fonts` for CJK glyphs
- Binaries wrap `LD_LIBRARY_PATH` (Wayland / X11 / Vulkan / dbus / alsa); on NixOS enable `hardware.graphics.enable`
- `pdfcraft` carries a temporary workaround for `rten-gemm` 0.26 vs rustc 1.98 / LLVM 21; it may need revisiting if that dependency bumps

```sh
nix fmt    # nixfmt-tree
nix flake update photocraft-src
```
