"""Manifest for data/holdout/ (context.md rejection round 4) — detects silent corpus drift.

data/holdout/ is gitignored and regenerable-only (see tests/test_acceptance_holdout.py's
module docstring on why it must never be iterated against or tuned to). If corpus/generate.py
ever changes and someone regenerates the holdout corpus, it silently becomes a DIFFERENT
corpus under the same directory name — any acceptance numbers measured against "the holdout"
from before that point are no longer comparable, and without this manifest nobody would
notice.

``data/holdout.manifest.json`` is TRACKED and committed (unlike ``data/holdout/`` itself):
the sha256 of every file in the corpus at generation time, plus the exact generator command
and the git commit of ``corpus/`` that produced it. ``verify`` is what the acceptance suite
calls; any drift is reported per-file — changed, missing, or an unexpected new file — never
just "something changed".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MANIFEST_PATH = Path("data/holdout.manifest.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _corpus_commit() -> str:
    """The most recent git commit that touched corpus/ — the exact generator version that
    produced (or would reproduce) this manifest's files."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "corpus/"],
        capture_output=True, text=True, check=True,
    )
    commit = result.stdout.strip()
    if not commit:
        raise RuntimeError("no git commit found touching corpus/ — is this a git repo?")
    return commit


def build(holdout_dir: Path, *, command: str) -> dict:
    """Build the manifest dict for every file currently in ``holdout_dir``."""
    files = {
        _relpath(p, holdout_dir): _sha256(p)
        for p in sorted(holdout_dir.rglob("*"))
        if p.is_file()
    }
    return {
        "generator_command": command,
        "corpus_commit": _corpus_commit(),
        "files": files,
    }


def verify(manifest: dict, holdout_dir: Path) -> list[str]:
    """Compare ``manifest`` against the files actually in ``holdout_dir`` right now.

    Returns a list of human-readable drift descriptions, one per affected file — empty means
    clean. Never collapses multiple problems into one summary line.
    """
    problems: list[str] = []
    expected = manifest["files"]
    actual_paths = {_relpath(p, holdout_dir) for p in holdout_dir.rglob("*") if p.is_file()}

    for name in sorted(expected):
        path = holdout_dir / name
        if not path.exists():
            problems.append(f"MISSING: {name} (in manifest, not found in data/holdout/)")
            continue
        actual_hash = _sha256(path)
        expected_hash = expected[name]
        if actual_hash != expected_hash:
            problems.append(
                f"CHANGED: {name} (manifest sha256 {expected_hash[:12]}... "
                f"!= actual {actual_hash[:12]}...)"
            )

    for name in sorted(actual_paths - set(expected)):
        problems.append(f"UNEXPECTED: {name} (present in data/holdout/, not in manifest)")

    return problems


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build data/holdout.manifest.json from the current data/holdout/ contents"
    )
    ap.add_argument("--holdout", type=Path, default=Path("data/holdout"))
    ap.add_argument(
        "--command", required=True,
        help="the exact command that generated data/holdout/, recorded verbatim",
    )
    ap.add_argument("--out", type=Path, default=MANIFEST_PATH)
    args = ap.parse_args(argv)

    if not args.holdout.is_dir():
        ap.error(f"holdout dir not found: {args.holdout}")

    manifest = build(args.holdout, command=args.command)
    args.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}: {len(manifest['files'])} files, "
          f"corpus commit {manifest['corpus_commit'][:12]}")


if __name__ == "__main__":
    main()
