#!/usr/bin/env python3
"""Which *Craft patches no longer match upstream?

`pkgs/patches/*.py` rewrite upstream Rust sources with plain string needles. A needle
that stops matching is a silent no-op in the build, so nothing tells us that storytold
has fixed (or moved) the code we patch. This compares every rule against two trees:

  pinned  the revision in flake.lock - what the packages build from today
  head    the upstream default branch - what the next `nix flake update` will build from

Per rule and app:

  in use   applies to `head`: the code we patch is still there
  DRIFT    applies to `pinned` but not to `head`: upstream changed or fixed that code
  new      applies to `head` but not to `pinned`: a needle starts matching new upstream code

`DRIFT` exits non-zero: read the upstream diff, and if the fix landed upstream, delete the
rule from its module in `pkgs/patches/` (and the vendored-egui ones from `vendor-egui.py`).
`new` is reported but not fatal.

The egui rules in `vendor-egui.py` are not checked here: they already fail the build
loudly ("expected exactly one match ... the vendored egui changed") when the crate moves.

Usage: patch-drift.py [--apps photocraft,designcraft] [--cache-dir DIR] [--summary FILE]
"""

import argparse
import importlib.util
import io
import json
import os
import pathlib
import sys
import tarfile
import time
import urllib.error
import urllib.request

# Loading the patcher would otherwise drop __pycache__ next to it in the repo.
sys.dont_write_bytecode = True

REPO = pathlib.Path(__file__).resolve().parents[2]
PATCHER = REPO / "pkgs" / "patches" / "engine.py"
LOCK = REPO / "flake.lock"
UA = "nixcraft-patch-drift"


def token():
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def request(url, *, api=False, retries=3) -> bytes:
    headers = {"User-Agent": UA}
    tok = token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    if api:
        headers["Accept"] = "application/vnd.github+json"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
                return bytes(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise SystemExit(f"not found: {url}")
            if attempt == retries - 1:
                raise SystemExit(f"{url}: HTTP {e.code}")
        except OSError as e:
            if attempt == retries - 1:
                raise SystemExit(f"{url}: {e}")
        time.sleep(3 * (attempt + 1))
    raise SystemExit(f"{url}: gave up")


def load_patcher():
    spec = importlib.util.spec_from_file_location("craft_patches", PATCHER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {PATCHER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # patch_egui_child_emoji bakes the emoji font path into the text it writes; the path
    # only has to be non-empty for a rule to fire, and the drift run never builds.
    os.environ.setdefault("NIXOS_EMOJI_TTF", "/nix/store/emoji/NotoEmoji-Regular.ttf")
    return mod


def locked_sources():
    """{name: {owner, repo, rev}} for every upstream input in flake.lock."""
    nodes = json.loads(LOCK.read_text())["nodes"]
    out = {}
    for name, node in nodes.items():
        if not (name.endswith("-src") or name == "craft-fonts"):
            continue
        locked = node.get("locked", {})
        if locked.get("type") != "github":
            continue
        out[name[: -len("-src")] if name.endswith("-src") else name] = {
            "owner": locked["owner"],
            "repo": locked["repo"],
            "rev": locked["rev"],
        }
    return out


def tarball(cache, owner, repo, ref, label):
    """Extract owner/repo at ref under <cache>/<repo>-<label> and return the tree root."""
    dest = cache / f"{repo}-{label}"
    if dest.is_dir():
        return dest
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    blob = request(url)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.name.count("/") >= 1 or m.isdir()]
        tops = {m.name.split("/", 1)[0] for m in members if "/" in m.name}
        if len(tops) != 1:
            raise SystemExit(f"{owner}/{repo}@{ref}: unexpected tarball layout {tops}")
        root = tops.pop()
        for member in members:
            rel = member.name.split("/", 1)
            if len(rel) < 2 or not rel[1]:
                continue
            member.name = rel[1]
            tar.extract(member, dest, filter="data")
    return dest


def default_branch_head(owner, repo):
    info = json.loads(request(f"https://api.github.com/repos/{owner}/{repo}", api=True))
    branch = info["default_branch"]
    commits = json.loads(request(f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}", api=True))
    return branch, commits["sha"]


def applied(mod, fn, tree):
    """The files a single rule rewrites in `tree`."""
    hits = []
    for path in mod.walk_rs(str(tree)):
        try:
            text = open(path, encoding="utf-8", errors="surrogateescape").read()
        except OSError:
            continue
        _, changed = fn(path, text)
        if changed:
            hits.append(os.path.relpath(path, tree))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", help="comma-separated subset (default: every input in flake.lock)")
    ap.add_argument("--cache-dir", default=os.environ.get("PATCH_DRIFT_CACHE", str(pathlib.Path.home() / ".cache" / "nixcraft-patch-drift")))
    ap.add_argument("--summary", help="write the report here as markdown (also $GITHUB_STEP_SUMMARY when set)")
    args = ap.parse_args()

    mod = load_patcher()
    rules = [(fn.__name__, fn) for fn in mod.RULES]
    cache = pathlib.Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    sources = locked_sources()
    if args.apps:
        wanted = {a.strip() for a in args.apps.split(",") if a.strip()}
        sources = {k: v for k, v in sources.items() if k in wanted}

    lines = []
    drift = []
    fresh = []
    for app, src in sorted(sources.items()):
        branch, head = default_branch_head(src["owner"], src["repo"])
        pinned = tarball(cache, src["owner"], src["repo"], src["rev"], src["rev"][:12])
        upstream = tarball(cache, src["owner"], src["repo"], head, head[:12])
        head_line = f"{app}  pinned {src['rev'][:12]} -> head {head[:12]} ({branch})"
        rows = []
        for name, fn in rules:
            at_pin = applied(mod, fn, pinned)
            at_head = applied(mod, fn, upstream)
            if not at_pin and not at_head:
                continue
            if at_head and at_pin:
                status, detail = "in use", ", ".join(sorted(set(at_head) & set(at_pin)) or at_head)
            elif at_head:
                status, detail = "new", ", ".join(sorted(at_head))
                fresh.append((app, name, detail))
            else:
                status, detail = "DRIFT", ", ".join(sorted(at_pin))
                drift.append((app, name, detail))
            rows.append(f"  {status:<7} {name:<26} {detail}")
        if rows:
            lines.append(head_line)
            lines.extend(rows)
            print(head_line)
            for row in rows:
                print(row)
        else:
            print(f"{app}: no rule applies at either revision")

    print(f"\n{len(sources)} apps checked, {len(drift)} drifted, {len(fresh)} newly matching")
    for app, name, detail in drift:
        print(f"DRIFT: {app}/{name} applied at the pinned revision and not at head ({detail}) - upstream fixed or moved it")
    for app, name, detail in fresh:
        print(f"NEW:   {app}/{name} matches upstream code it did not match before ({detail})")

    report = "\n".join(lines + ["", f"{len(sources)} apps checked, {len(drift)} drifted, {len(fresh)} newly matching"])
    if args.summary:
        pathlib.Path(args.summary).write_text(report + "\n")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary and not args.summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("## Patch drift\n\n```\n" + report + "\n```\n")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
