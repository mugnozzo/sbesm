import os
from pathlib import Path

from sbesm.scanner import walk_root

# --- 2.2.1 scope-respecting walker, excludes .sbesm/partial-dir at any depth


def test_excludes_sbesm_and_partial_dir_at_any_depth(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / ".sbesm").mkdir()
    (root / ".sbesm" / "index.sqlite").write_text("x")
    (root / "photos").mkdir()
    (root / "photos" / ".sbesm").mkdir()  # decoy nested at depth 2
    (root / "photos" / ".sbesm" / "fake.sqlite").write_text("x")
    (root / "photos" / ".rsync-partial").mkdir()
    (root / "photos" / ".rsync-partial" / "partial.tmp").write_text("x")
    (root / "photos" / "a.jpg").write_text("data")
    (root / "sbesmdecoy").mkdir()  # not literally named .sbesm -> must be included
    (root / "sbesmdecoy" / "keep.txt").write_text("data")

    entries = walk_root(root)
    paths = {e.relative_path for e in entries}

    assert "photos/a.jpg" in paths
    assert "sbesmdecoy/keep.txt" in paths
    assert not any(p.startswith(".sbesm") for p in paths)
    assert not any(".sbesm" in p for p in paths)
    assert not any(".rsync-partial" in p for p in paths)


def test_scope_restricts_to_selected_subtree(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "photos").mkdir()
    (root / "photos" / "a.jpg").write_text("x")
    (root / "documents").mkdir()
    (root / "documents" / "b.txt").write_text("y")

    entries = walk_root(root, scope=["photos"])
    paths = {e.relative_path for e in entries}
    assert paths == {"photos/a.jpg"}


def test_scope_with_individual_file_selector(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "documents").mkdir()
    (root / "documents" / "notes.txt").write_text("y")
    (root / "documents" / "other.txt").write_text("z")

    entries = walk_root(root, scope=["documents/notes.txt"])
    paths = {e.relative_path for e in entries}
    assert paths == {"documents/notes.txt"}


# --- 2.2.2 entry classification (symlinks, never followed) -----------------


def test_symlink_is_classified_and_target_recorded_without_following(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    real_dir = root / "real_dir"
    real_dir.mkdir()
    (real_dir / "inside.txt").write_text("secret")
    link = root / "link_to_dir"
    link.symlink_to(real_dir)

    real_file = root / "real_file.txt"
    real_file.write_text("hello")
    file_link = root / "link_to_file"
    file_link.symlink_to(real_file)

    entries = walk_root(root)
    by_path = {e.relative_path: e for e in entries}

    assert by_path["link_to_dir"].kind == "symlink"
    assert by_path["link_to_dir"].symlink_target == str(real_dir)
    # must never descend into a symlinked directory
    assert "link_to_dir/inside.txt" not in by_path

    assert by_path["link_to_file"].kind == "symlink"
    assert by_path["link_to_file"].symlink_target == str(real_file)


# --- 2.2.4 unreadable-entry handling, scan continues ------------------------


def test_unreadable_entry_is_marked_and_scan_continues(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "good.txt").write_text("ok")
    (root / "bad.txt").write_text("irrelevant")

    original_lstat = Path.lstat

    def flaky_lstat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self.name == "bad.txt":
            raise OSError("permission denied (simulated)")
        return original_lstat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", flaky_lstat)

    entries = walk_root(root)
    by_path = {e.relative_path: e for e in entries}
    assert by_path["bad.txt"].kind == "unreadable"
    assert by_path["good.txt"].kind == "regular"


# --- 2.2.5 deterministic ordering -------------------------------------------


def test_scan_ordering_is_deterministic(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "b.txt").write_text("1")
    (root / "a.txt").write_text("2")
    (root / "sub").mkdir()
    (root / "sub" / "z.txt").write_text("3")

    first = [e.relative_path for e in walk_root(root)]
    second = [e.relative_path for e in walk_root(root)]
    assert first == second == sorted(first)
