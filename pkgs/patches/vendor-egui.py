#!/usr/bin/env python3
"""Patch the vendored egui that every *Craft app builds against.

Usage: vendor-egui.py <writable cargo vendor dir>

The vendor dir is the writable copy nixpkgs' cargoSetupPostUnpackHook makes in
the build tree (``$cargoDepsCopy``). ``importCargoLock`` writes
``{"files":{},...}`` as the crate checksum file, so editing files here does not
break cargo's verification.

Two egui 0.36.2 behaviours break the apps on NixOS/Wayland:

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


def patch_file(path, old, new, label):
    with open(path, encoding="utf-8", errors="surrogateescape") as handle:
        text = handle.read()
    if new in text:
        print(f"vendor-egui: {label} already patched")
        return
    if text.count(old) != 1:
        raise SystemExit(
            f"vendor-egui: {label}: expected exactly one match in {path}, "
            f"found {text.count(old)} - the vendored egui changed, re-check it"
        )
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as handle:
        handle.write(text.replace(old, new))
    print(f"vendor-egui: patched {label} in {path}")


def main(argv):
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} <cargo vendor dir>")
    vendor = argv[1]
    if not os.path.isdir(vendor):
        raise SystemExit(f"vendor-egui: no such directory: {vendor}")

    crates = sorted(
        name
        for name in os.listdir(vendor)
        # `egui-0.36.2`, but not `egui-wgpu-0.36.2` / `egui-winit-0.36.2`.
        if name == "egui" or (name.startswith("egui-") and name[5:6].isdigit())
    )
    if not crates:
        raise SystemExit(f"vendor-egui: no egui crate under {vendor}")
    for crate in crates:
        memory = os.path.join(vendor, crate, "src", "memory", "mod.rs")
        context = os.path.join(vendor, crate, "src", "context.rs")
        for path in (memory, context):
            if not os.path.isfile(path):
                raise SystemExit(f"vendor-egui: missing {path}")
        patch_file(memory, MEMORY_REQUEST_FOCUS_OLD, MEMORY_REQUEST_FOCUS_NEW,
                   f"{crate} request_focus/IME")
        patch_file(context, CONTEXT_FOCUS_OLD, CONTEXT_FOCUS_NEW,
                   f"{crate} accesskit focus")


if __name__ == "__main__":
    main(sys.argv)
