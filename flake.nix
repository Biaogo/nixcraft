{
  description = "nixcraft — Nix flake packaging the storytold *Craft apps";

  inputs = {
    # Craft apps need Rust edition 2024 / rustc >= 1.95; track nixos-unstable.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    craft-fonts = {
      url = "github:storytold/craft-fonts";
      flake = false;
    };
    photocraft-src = {
      url = "github:storytold/photocraft";
      flake = false;
    };
    pdfcraft-src = {
      url = "github:storytold/pdfcraft";
      flake = false;
    };
    filmcraft-src = {
      url = "github:storytold/filmcraft";
      flake = false;
    };
    lightcraft-src = {
      url = "github:storytold/lightcraft";
      flake = false;
    };
    wordcraft-src = {
      url = "github:storytold/wordcraft";
      flake = false;
    };
    vectorcraft-src = {
      url = "github:storytold/vectorcraft";
      flake = false;
    };
    effectcraft-src = {
      url = "github:storytold/effectcraft";
      flake = false;
    };
    gridcraft-src = {
      url = "github:storytold/gridcraft";
      flake = false;
    };
    cadcraft-src = {
      url = "github:storytold/cadcraft";
      flake = false;
    };
    designcraft-src = {
      url = "github:storytold/designcraft";
      flake = false;
    };
    deckcraft-src = {
      url = "github:storytold/deckcraft";
      flake = false;
    };
    soundcraft-src = {
      url = "github:storytold/soundcraft";
      flake = false;
    };
    figcraft-src = {
      url = "github:storytold/figcraft";
      flake = false;
    };
    artcraft-src = {
      url = "github:storytold/artcraft";
      flake = false;
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      craft-fonts,
      ...
    }@inputs:
    let
      inherit (nixpkgs) lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      specs = import ./pkgs/default.nix { inherit inputs; };
      mkAll =
        pkgs:
        let
          craftFonts = pkgs.callPackage ./pkgs/craft-fonts-glyf.nix { inherit craft-fonts; };
          mkCraft = pkgs.callPackage ./pkgs/mk-craft.nix { craft-fonts = craftFonts; };
          each = lib.mapAttrs (name: spec: mkCraft ({ pname = name; } // spec)) specs;
          artcraft = pkgs.callPackage ./pkgs/artcraft.nix { src = inputs.artcraft-src; };
          named = each // {
            inherit artcraft;
          };
        in
        named
        // {
          all = pkgs.symlinkJoin {
            name = "nixcraft-all";
            paths = builtins.attrValues named;
          };
        };
      forAllSystems = f: lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      overlays.default =
        final: _prev: removeAttrs (mkAll final) [ "all" ] // { nixcraft-all = (mkAll final).all; };

      packages = forAllSystems (
        pkgs:
        let
          p = mkAll pkgs;
        in
        p // { default = p.all; }
      );

      apps = forAllSystems (
        pkgs:
        lib.mapAttrs
          (_: drv: {
            type = "app";
            program = lib.getExe drv;
          })
          (
            removeAttrs self.packages.${pkgs.system} [
              "all"
              "default"
            ]
          )
      );

      formatter = forAllSystems (pkgs: pkgs.nixfmt-tree);
    };
}
