#!/usr/bin/env python3
"""Patch the egui crate that every *Craft app builds against.

Usage: vendor-egui.py <writable cargo vendor dir> [source root]

Most apps resolve egui from crates.io or git, so nixpkgs'
cargoSetupPostUnpackHook leaves a writable copy under ``$cargoDepsCopy``.
``importCargoLock`` writes ``{"files":{},...}`` as the crate checksum file, so
editing files there does not break cargo's verification. Some apps (e.g.
SolidCraft v0.46+) instead vendor egui in-tree via a ``path = ...`` entry in
``Cargo.toml`` (``[patch.crates-io]``), which ``importCargoLock`` does not copy
into the vendor dir; passing ``[source root]`` discovers those in-tree copies as
well.

egui 0.36.2 needs both rules on NixOS/Wayland. Upstream egui 0.37.0 (crates.io,
and SolidCraft's in-tree vendor/egui) fixes the accesskit TreeUpdate focus issue
but still interrupts IME unconditionally in ``request_focus``; the storytold/egui
fork carries both fixes. The script skips a rule whose upstream-fixed form is
already present instead of failing.

1. ``Memory::request_focus`` calls ``interrupt_ime()`` unconditionally, and
   therefore also on a no-op re-request. Several dialogs (GridCraft's command
   palette, WordCraft's command palette, VectorCraft's search) call
   ``Response::request_focus()`` from inside a body that runs every frame, so
   the IME is interrupted on every frame and fcitx5 immediately closes the
   candidate window - the input method can never be raised. Only a real focus
   *change* is supposed to interrupt composition.

2. The accesskit ``TreeUpdate`` publishes ``Memory::focused()`` even when no
   node was built for that id. FigCraft requests focus for its page-rename
   field in the frame the double click arrives, one frame before the field is
   drawn, and accesskit_consumer panics with
   ``Focused ID ... is not in the node list``.
"""

import os
import sys
import tomllib

MEMORY_REQUEST_FOCUS_OLD = """    /// Give keyboard focus to a specific widget.
    /// See also [`crate::Response::request_focus`].
    ///
    /// Calling this will interrupt IME composition.
    #[inline(always)]
    pub fn request_focus(&mut self, id: Id) {
        self.focus_mut().focused_widget = Some(FocusWidget::new(id));
        self.interrupt_ime();
    }
"""

MEMORY_REQUEST_FOCUS_NEW = """    /// Give keyboard focus to a specific widget.
    /// See also [`crate::Response::request_focus`].
    ///
    /// Calling this will interrupt IME composition, but only when `id` does
    /// not already have focus. Widgets that re-request focus on every frame
    /// (search and command dialogs) would otherwise kill the IME session at
    /// the end of the frame in which the user raises it.
    #[inline(always)]
    pub fn request_focus(&mut self, id: Id) {
        if self.focused() == Some(id) {
            return;
        }
        self.focus_mut().focused_widget = Some(FocusWidget::new(id));
        self.interrupt_ime();
    }
"""

MEMORY_REQUEST_FOCUS_FIXED = """    pub fn request_focus(&mut self, id: Id) {
        if self.focused() != Some(id) {
            self.interrupt_ime();
        }
        self.focus_mut().focused_widget = Some(FocusWidget::new(id));
    }
"""

CONTEXT_FOCUS_OLD = """                let nodes = {
                    state
                        .nodes
                        .into_iter()
                        .map(|(id, node)| (id.accesskit_id(), node))
                        .collect()
                };
                let focus_id = self
                    .memory
                    .focused()
                    .map_or(root_id, |id| id.accesskit_id());
"""

CONTEXT_FOCUS_FIXED = """                let focus_id = self
                    .memory
                    .focused()
                    .filter(|id| state.nodes.contains_key(id))
                    .map_or(root_id, |id| id.accesskit_id());"""

CONTEXT_FOCUS_NEW = """                // The explicit type keeps inference happy now that `nodes` is read before it is
                // moved into the update below.
                let nodes: Vec<(accesskit::NodeId, accesskit::Node)> = {
                    state
                        .nodes
                        .into_iter()
                        .map(|(id, node)| (id.accesskit_id(), node))
                        .collect()
                };
                // A widget can be given focus one frame before it is drawn
                // (FigCraft does that when a page rename starts). accesskit
                // panics when the focus id has no node, so keep the root
                // focused until the widget actually shows up.
                let focus_id = self
                    .memory
                    .focused()
                    .map(|id| id.accesskit_id())
                    .filter(|id| nodes.iter().any(|(node_id, _)| node_id == id))
                    .unwrap_or(root_id);
"""


def patch_file(old, new, fixed, label, path):
    with open(path, encoding="utf-8", errors="surrogateescape") as handle:
        text = handle.read()
    if new in text:
        print(f"vendor-egui: {label} already patched")
        return
    if fixed in text:
        print(f"vendor-egui: {label} fixed upstream, nothing to patch")
        return
    n = text.count(old)
    if n != 1:
        raise SystemExit(
            f"vendor-egui: {label}: expected exactly one match in {path}, "
            f"found {n} - the vendored egui changed, re-check it"
        )
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as handle:
        handle.write(text.replace(old, new))
    print(f"vendor-egui: patched {label} in {path}")


def is_egui_dir(name):
    # `egui-0.36.2`, but not `egui-wgpu-0.36.2` / `egui-winit-0.36.2`.
    return name == "egui" or (name.startswith("egui-") and name[5:6].isdigit())


def vendor_egui_dirs(vendor):
    crates = []
    for name in sorted(os.listdir(vendor)):
        path = os.path.join(vendor, name)
        if not os.path.isdir(path):
            continue
        if is_egui_dir(name):
            crates.append((name, path))
        elif name.startswith("dup-") and name[4:].isdigit():
            for sub in sorted(os.listdir(path)):
                subpath = os.path.join(path, sub)
                if is_egui_dir(sub) and os.path.isdir(subpath):
                    crates.append((f"{name}/{sub}", subpath))
    return crates


def iter_dep_tables(manifest):
    for table in manifest.get("patch", {}).values():
        if isinstance(table, dict):
            yield table
    ws_deps = manifest.get("workspace", {}).get("dependencies")
    if isinstance(ws_deps, dict):
        yield ws_deps
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        deps = manifest.get(section)
        if isinstance(deps, dict):
            yield deps
    for target in manifest.get("target", {}).values():
        if isinstance(target, dict):
            for section in ("dependencies", "dev-dependencies", "build-dependencies"):
                deps = target.get(section)
                if isinstance(deps, dict):
                    yield deps


def source_egui_dirs(source_root):
    crates = []
    root_manifest = os.path.realpath(os.path.join(source_root, "Cargo.toml"))
    for directory, dirnames, filenames in os.walk(source_root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in {".git", "target", "vendor", "node_modules"}
        )
        if "Cargo.toml" not in filenames:
            continue
        manifest_path = os.path.join(directory, "Cargo.toml")
        try:
            with open(manifest_path, "rb") as handle:
                manifest = tomllib.load(handle)
        except tomllib.TOMLDecodeError:
            if os.path.realpath(manifest_path) == root_manifest:
                raise
            continue
        for table in iter_dep_tables(manifest):
            for key, spec in table.items():
                if not isinstance(spec, dict):
                    continue
                if spec.get("package", key) != "egui":
                    continue
                rel = spec.get("path")
                if not isinstance(rel, str):
                    continue
                crate_dir = os.path.normpath(os.path.join(directory, rel))
                label = os.path.relpath(crate_dir, source_root)
                crates.append((label, crate_dir))
    return crates


def main(argv):
    if len(argv) not in (2, 3):
        raise SystemExit(f"usage: {argv[0]} <cargo vendor dir> [source root]")
    vendor = argv[1]
    source_root = argv[2] if len(argv) == 3 else None
    if not os.path.isdir(vendor):
        raise SystemExit(f"vendor-egui: no such directory: {vendor}")
    if source_root is not None and not os.path.isdir(source_root):
        raise SystemExit(f"vendor-egui: no such directory: {source_root}")

    candidates = vendor_egui_dirs(vendor)
    if source_root is not None:
        candidates.extend(source_egui_dirs(source_root))

    crates = []
    seen = set()
    for label, crate_dir in candidates:
        real = os.path.realpath(crate_dir)
        if real not in seen:
            seen.add(real)
            crates.append((label, crate_dir))

    if not crates:
        where = f"{vendor} or {source_root}" if source_root is not None else vendor
        raise SystemExit(f"vendor-egui: no egui crate under {where}")
    for label, crate_dir in crates:
        memory = os.path.join(crate_dir, "src", "memory", "mod.rs")
        context = os.path.join(crate_dir, "src", "context.rs")
        for path in (memory, context):
            if not os.path.isfile(path):
                raise SystemExit(f"vendor-egui: missing {path}")
        patch_file(
            MEMORY_REQUEST_FOCUS_OLD,
            MEMORY_REQUEST_FOCUS_NEW,
            MEMORY_REQUEST_FOCUS_FIXED,
            f"{label} request_focus/IME",
            memory,
        )
        patch_file(
            CONTEXT_FOCUS_OLD,
            CONTEXT_FOCUS_NEW,
            CONTEXT_FOCUS_FIXED,
            f"{label} accesskit focus",
            context,
        )


if __name__ == "__main__":
    main(sys.argv)
