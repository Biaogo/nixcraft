#!/usr/bin/env python3
"""Remove unused Cargo patch entries for crates absent from the vendor tree.

Starting with wordcraft v0.12.0, the apps' Cargo.toml files redirect many
crates to git forks through [patch.crates-io]. Some of those crates are not in
Cargo.lock, so importCargoLock never vendors them. Cargo still checks every
patch source against the vendor directory provided by Nix and fails resolution
when a matching crate is missing. Dropping a patch entry for a crate that the
lock never resolves does not change the build, so this script removes exactly
those unused entries while keeping patches for vendored crates intact.

Path patches are local sources and are never pruned. A git patch is pruned
only when Cargo.lock itself marks that patch unused.

Cargo records patches it did not use as [[patch.unused]] entries in
Cargo.lock. Removing a Cargo.toml patch without removing its lock record makes
Cargo want to update the lock, which fails for builds using --locked. nixpkgs
also diffs the source Cargo.lock against the vendor copy, so both are pruned
together.
"""

import os
import re
import sys


ENTRY_RE = re.compile(r"^(?P<name>[A-Za-z0-9_-]+)\s*=\s*\{")
BARE_KEY_RE = re.compile(r"^(?P<name>[A-Za-z0-9_-]+)\s*=")
TABLE_RE = re.compile(r"^\[(?P<table>patch\.[^\]]+)\]")
LOCK_KEY_RE = re.compile(rb"^[A-Za-z0-9_-]+\s*=")
LOCK_NAME_RE = re.compile(rb'^name\s*=\s*"(?P<name>[^"]+)"\s*$')


def read_patch_unused_names(path):
    try:
        with open(path, "rb") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return set()

    names = set()
    index = 0
    while index < len(lines):
        if lines[index].rstrip(b"\r\n") != b"[[patch.unused]]":
            index += 1
            continue

        end = index + 1
        while end < len(lines) and LOCK_KEY_RE.match(lines[end]):
            match = LOCK_NAME_RE.match(lines[end].rstrip(b"\r\n"))
            if match:
                names.add(match.group("name").decode("ascii"))
            end += 1
        index = end

    return names


def prune_lock(path, dropped_names, source_root):
    try:
        with open(path, "rb") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return

    kept = []
    removed = []
    index = 0
    while index < len(lines):
        if lines[index].rstrip(b"\r\n") != b"[[patch.unused]]":
            kept.append(lines[index])
            index += 1
            continue

        end = index + 1
        name = None
        while end < len(lines) and LOCK_KEY_RE.match(lines[end]):
            match = LOCK_NAME_RE.match(lines[end].rstrip(b"\r\n"))
            if match:
                name = match.group("name").decode("ascii")
            end += 1

        if name in dropped_names:
            removed.append(name)
            if end < len(lines) and lines[end] in {b"\n", b"\r\n"}:
                end += 1
            index = end
            continue

        kept.append(lines[index])
        index += 1

    if removed:
        with open(path, "wb") as handle:
            handle.writelines(kept)
        relpath = os.path.relpath(path, source_root)
        for name in removed:
            print(
                f"cargo-patch-prune: dropped the [[patch.unused]] record "
                f"for {name} from {relpath}"
            )


def main(argv):
    if len(argv) != 3:
        raise SystemExit(
            f"usage: {argv[0]} <source root> <cargo vendor dir>"
        )

    source_root, vendor = argv[1:]
    with os.scandir(vendor) as entries:
        vendor_dirs = {entry.name for entry in entries if entry.is_dir()}

    for directory, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in {".git", "target", "vendor", "node_modules"}
        ]
        if "Cargo.toml" not in filenames:
            continue

        path = os.path.join(directory, "Cargo.toml")
        with open(path, encoding="utf-8", errors="surrogateescape") as handle:
            lines = handle.readlines()
        if not any(line.startswith("[patch") for line in lines):
            continue

        unused_patch_names = read_patch_unused_names(
            os.path.join(directory, "Cargo.lock")
        )
        table = None
        kept = []
        dropped = []
        for line in lines:
            if line.startswith("["):
                match = TABLE_RE.match(line)
                table = match.group("table") if match else None

            if table is not None:
                match = ENTRY_RE.match(line)
                if match and line.rstrip().endswith("}"):
                    name = match.group("name")
                    is_vendored = any(
                        vendor_name.startswith(f"{name}-")
                        for vendor_name in vendor_dirs
                    )
                    if "path = " in line:
                        pass
                    elif "git = " in line and not is_vendored:
                        if name not in unused_patch_names:
                            relpath = os.path.relpath(path, source_root)
                            raise SystemExit(
                                f"cargo-patch-prune: {relpath}: {name} is "
                                "patched from git but neither vendored nor "
                                "[[patch.unused]] in Cargo.lock - inspect it "
                                "before pruning"
                            )
                        dropped.append((name, table))
                        continue
                    elif not is_vendored:
                        dropped.append((name, table))
                        continue
                elif match or (bare_key := BARE_KEY_RE.match(line)):
                    name = match.group("name") if match else bare_key.group("name")
                    relpath = os.path.relpath(path, source_root)
                    raise SystemExit(
                        f"cargo-patch-prune: {relpath}: cannot rewrite the "
                        f"multi-line entry for {name} in [{table}] - extend "
                        "this script"
                    )

            kept.append(line)

        if dropped:
            with open(
                path, "w", encoding="utf-8", errors="surrogateescape"
            ) as handle:
                handle.writelines(kept)
            relpath = os.path.relpath(path, source_root)
            for name, table in dropped:
                print(
                    f"cargo-patch-prune: dropped {name} from [{table}] in "
                    f"{relpath} (not in the vendor dir)"
                )

            dropped_names = {name for name, _ in dropped}
            lock_paths = [os.path.join(directory, "Cargo.lock")]
            vendor_lock = os.path.join(vendor, "Cargo.lock")
            if os.path.isfile(vendor_lock):
                lock_paths.append(vendor_lock)

            seen = set()
            for lock_path in lock_paths:
                realpath = os.path.realpath(lock_path)
                if realpath not in seen:
                    prune_lock(lock_path, dropped_names, source_root)
                    seen.add(realpath)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
