"""eval/manifest.py — sha256 drift detection for data/holdout/ (context.md rejection round 4).

data/holdout/ is gitignored and regenerable-only. If corpus/generate.py ever changes and
someone regenerates it, the directory silently becomes a DIFFERENT corpus under the same
name, and any acceptance numbers measured against "the holdout" stop being comparable. The
manifest (TRACKED, committed — unlike data/holdout/ itself) pins the sha256 of every file at
generation time; ``verify`` must catch a changed file, a missing file, and an unexpected new
file, each named individually.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from eval.manifest import build, verify


@pytest.fixture
def holdout_dir(tmp_path):
    d = tmp_path / "holdout"
    d.mkdir()
    (d / "a.gt.json").write_text('{"x": 1}', encoding="utf-8")
    (d / "b.docx").write_bytes(b"fake docx bytes")
    return d


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_build_records_sha256_of_every_file(holdout_dir):
    manifest = build(holdout_dir, command="python -m corpus.generate --seed 1337")
    assert manifest["files"]["a.gt.json"] == _sha256_bytes(b'{"x": 1}')
    assert manifest["files"]["b.docx"] == _sha256_bytes(b"fake docx bytes")
    assert len(manifest["files"]) == 2


def test_build_records_generator_command_and_corpus_commit(holdout_dir):
    manifest = build(holdout_dir, command="python -m corpus.generate --seed 1337")
    assert manifest["generator_command"] == "python -m corpus.generate --seed 1337"
    assert isinstance(manifest["corpus_commit"], str)
    assert len(manifest["corpus_commit"]) == 40  # full git sha


def test_verify_is_clean_when_nothing_changed(holdout_dir):
    manifest = build(holdout_dir, command="x")
    assert verify(manifest, holdout_dir) == []


def test_verify_reports_changed_file_by_name(holdout_dir):
    manifest = build(holdout_dir, command="x")
    (holdout_dir / "a.gt.json").write_text('{"x": 2}', encoding="utf-8")
    problems = verify(manifest, holdout_dir)
    assert len(problems) == 1
    assert "a.gt.json" in problems[0]
    assert "CHANGED" in problems[0]


def test_verify_reports_missing_file_by_name(holdout_dir):
    manifest = build(holdout_dir, command="x")
    (holdout_dir / "b.docx").unlink()
    problems = verify(manifest, holdout_dir)
    assert len(problems) == 1
    assert "b.docx" in problems[0]
    assert "MISSING" in problems[0]


def test_verify_reports_unexpected_new_file_by_name(holdout_dir):
    manifest = build(holdout_dir, command="x")
    (holdout_dir / "c_new.pdf").write_bytes(b"new file not in manifest")
    problems = verify(manifest, holdout_dir)
    assert len(problems) == 1
    assert "c_new.pdf" in problems[0]
    assert "UNEXPECTED" in problems[0]


def test_manifest_round_trips_through_json(holdout_dir):
    manifest = build(holdout_dir, command="x")
    reloaded = json.loads(json.dumps(manifest))
    assert verify(reloaded, holdout_dir) == []
