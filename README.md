# SBESM — Simple But Easy Synchronization Manager

A conservative, one-way file synchronization and integrity-checking CLI for
multiple computers, disks and partitions.

## Why SBESM?
rsync is a really cool tool, and I use it a lot.
But I also needed a more automated (but not too automated) syncronization tool, that beside synchronizing, would create an index of the files, check checksums on a single storage, and other stuff.
Many syncronization apps can be found online, but I needed one tailored on my specific needs.
That's where, when and why SBESM comes out.

## What is SBESM?

SBESM helps you keep the same files consistent across several disks,
partitions or machines, and catch silent corruption before it spreads. It
builds a content-hash index for each storage, lets you compare and
one-way-sync any two storages over `rsync`, and always previews what it's
about to do before it does it. It's aimed at anyone who manages more than
one copy of the same data — backups, archives, mirrored drives — and wants
to *see* what will change before committing to it, rather than trusting a
sync tool to just get it right.

**SBESM is not a backup tool.** It helps you keep several disks' contents
in sync and catch silent corruption, but a sync can propagate a mistake (an
accidental overwrite, a bad `--delete --apply`) to every copy just as fast
as it propagates a good change. Keep an independent, versioned/offline
backup of anything you can't afford to lose — SBESM assumes one exists and
doesn't try to be it.

**`sync`/`reconcile` have no transactional rollback.** Each is a sequence
of independent per-selector (or per-file) operations, not one atomic unit.
If one selector's `rsync` invocation fails partway through a multi-selector
`--apply`, whatever already succeeded on other selectors stays applied —
`sync` doesn't undo it. A failed selector is still reported (per-selector
output, plus an overall `IO_FAILURE` exit code), so a failure is never
silent, but don't assume all-or-nothing: check what actually happened
rather than inferring it from the exit code alone.

## Features

- **Content-hash indexing and verification** — `index` builds a reference
  index of every file's hash and metadata; `verify` always re-hashes
  on-disk content against that reference, so it catches silent corruption
  that a cheap size/mtime check would miss.
- **One-way sync over `rsync`** — `sync` previews what would change by
  default; nothing is copied, deleted or overwritten until you pass
  `--apply`, and deletion needs `--delete --apply` together, never either
  alone.
- **Explicit conflict handling** — a file that differs in content on both
  sides is never silently resolved; `sync --apply` refuses until you pass
  `--overwrite-conflicts`, or you `accept` a new reference on the side you
  trust.
- **Duplicate detection** — `duplicates` finds files sharing identical
  content within a storage, with an optional `--verify` pass to confirm
  matches by re-hashing rather than trusting the index alone.
- **mtime reconciliation** — `reconcile` aligns modification times between
  two storages, but only for files it has *proven* byte-identical first.
- **Per-storage exclude patterns** — opt into skipping names like `.venv`,
  `__pycache__` or `node_modules` everywhere: scanning, indexing,
  verifying, diffing, duplicate detection and syncing. A local defaults
  file can seed the same patterns into every newly created storage
  automatically.
- **Symlink-escape protection** — a selector that turns out to be a
  symlink pointing outside its storage's root is refused before `sync`
  (or any other command) touches it.
- **A local registry** — `register` a storage once and refer to it by name
  (`backup1`) instead of a full path everywhere after.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Requires Python 3.11+ and the `rsync` binary on `PATH` (only needed for
`sync`; every other command is pure Python).

## Commands at a glance

| Command | Purpose |
|---|---|
| `init` | Initialize a new managed storage root |
| `register` | Register an already-initialized storage under a name |
| `unregister` | Remove a storage from the local registry |
| `uninit` | Remove a storage's `.sbesm` directory (destructive) |
| `storages` | List registered storages |
| `index` | Index files and detect changes |
| `status` | Show storage status (categories, counts, last run times) |
| `verify` | Verify indexed files against their reference hashes |
| `accept` | Accept a new reference hash for a file |
| `duplicates` | Report files sharing identical content |
| `diff` | Compare two storages |
| `sync` | One-way synchronization from `SOURCE` to `DEST` |
| `reconcile` | Reconcile mtimes between two storages for proven-equal content |

Every mutating command defaults to a dry-run preview; nothing on disk
changes until you add `--apply`. `sync --delete` alone is *still* a
preview — only `--delete --apply` together actually remove anything.
`unregister` and `uninit` are the two exceptions to that flag-only
pattern: since they're hard to undo, each also asks for an interactive
`y/N` confirmation right before acting (pass `-y`/`--yes` to skip the
prompt from a script).

## Configuration

Each managed storage root gets its own `.sbesm/` directory:

```
/mnt/backup/archive/
├── documents/
├── photos/
├── .sbesm/
│   ├── config.toml      # per-storage identity, categories, profiles
│   ├── storage_id        # plaintext marker, cross-checked against config.toml
│   ├── index.sqlite      # this storage's own file index — never centralized
│   └── logs/             # one timestamped log per index/verify/sync/reconcile run
```

`config.toml` looks like:

```toml
[storage]
id = "<generated UUID>"
name = "backup1"
filesystem_uuid = "<detected block-device UUID, or empty if undetectable>"

[categories]
known = ["documents", "photos"]

[profiles.work]
categories = ["documents", "other"]

[sync]
preserve_partial = true
delete_by_default = false
# mtime_tolerance_ns = 2000000   # optional override; auto-detected by filesystem otherwise

[hashing]
algorithm = "sha256"

[exclude]
patterns = []   # e.g. [".venv", "__pycache__", "*.pyc", "node_modules"]
```

Sample files for all config shapes below live in `examples/`.

Three more config files live outside any single storage, under
`$XDG_CONFIG_HOME/sbesm/` (default `~/.config/sbesm/`):

- `registry.toml` — maps names you choose to storage IDs and last-known roots,
  so you can write `sbesm status backup1` instead of a full path. Purely a
  convenience cache; re-run `sbesm register` if a storage moves.
- `profiles.toml` — profiles that apply across *any* storage (by category
  name), taking precedence over a profile of the same name embedded in a
  storage's own `config.toml`.
- `defaults.toml` — an `[exclude] patterns = [...]` list copied into every
  new storage's own `config.toml` the moment you run `sbesm init`, so you
  don't have to hand-edit the same exclude patterns (e.g. `.venv`,
  `__pycache__`) into every disk separately. It's a one-time seed, not a
  live link: editing `defaults.toml` later only affects storages
  initialized afterward — each storage's `config.toml` is independent from
  then on, so you can still add to or remove from a particular storage's
  own list without touching the local default.

## Getting started

```bash
# one-time setup per disk
sbesm init /mnt/backup1 --name backup1
sbesm register /mnt/backup1 --name backup1
sbesm storages                              # see what's registered & available

# index: build/update the integrity reference (preview by default)
sbesm index backup1                         # dry run, shows what would change
sbesm index backup1 --apply                 # commits new/changed metadata
sbesm index backup1 --rehash --apply         # force re-hash even if size/mtime match

# check things are actually still what you think they are
sbesm verify backup1                        # always re-hashes every indexed file
sbesm status backup1                        # categories, counts, last run times
sbesm duplicates backup1 --verify           # find & confirm duplicate content

# compare and copy between two storages
sbesm diff backup1 backup2 --all
sbesm sync backup1 backup2 --all                       # preview only
sbesm sync backup1 backup2 --all --apply               # copy new/changed, never delete
sbesm sync backup1 backup2 --all --delete --apply      # also remove dest-only files
sbesm reconcile backup1 backup2 --all --apply           # align mtimes of proven-identical files

# undo: stop managing a storage
sbesm unregister backup1                    # just drop it from the local registry
sbesm uninit backup1 --apply                # also delete backup1's .sbesm/ (your files aren't touched)
```

`unregister` doesn't need the storage to be currently mounted — it just
drops a stale registry entry pointing at a disk that's already gone;
`uninit` does need to reach the real path, since it actually deletes
`.sbesm/` there (and, if that storage happened to be registered, cleans up
the now-stale registry entry too). `uninit` only prompts for confirmation
once `--apply` is passed, after showing what it would remove; `unregister`
prompts immediately, since it only ever touches `registry.toml`.

## Examples

### Resolving a detected conflict

```bash
$ sbesm sync backup1 backup2 --all --apply
error: 1 content conflict(s) detected; pass --overwrite-conflicts to apply
anyway, or resolve them first. Conflicting paths: ['documents/notes.txt']

$ sbesm diff backup1 backup2 --folder documents    # inspect first
$ sbesm sync backup1 backup2 --all --apply --overwrite-conflicts   # once you're sure
```

### Selector safety

Before touching anything, `sync` checks that every selector's resolved path
(on both the source and destination side) actually stays inside that
storage's root. This catches a selector whose top-level entry has become a
symlink pointing somewhere else entirely — accidental or malicious — before
`rsync` ever runs on it, in preview and in `--apply` alike:

```
$ sbesm sync backup1 backup2 --folder documents --apply
error: selector 'documents' resolves outside the storage root (possibly via
a symlink): /mnt/backup1/documents -> /etc
```

A symlink that resolves to somewhere *inside* the same storage root is
still allowed — only an actual escape is refused.

### Excluding files and folders

A storage's `config.toml` can opt into an `[exclude] patterns = [...]`
list — names/globs (e.g. `.venv`, `__pycache__`, `*.pyc`, `node_modules`)
matched against each individual file/directory *name* at any depth, not
the full path, so `[".venv"]` also excludes a nested `project/.venv`.
Nothing is excluded by default. An excluded path is invisible to `index`,
`verify`, `diff`, `duplicates` (which only ever sees what's indexed), and
`sync` — including `sync`'s underlying `rsync` call, so an excluded
directory inside an explicitly-selected folder is never physically copied.
This only affects *automatic* discovery (`--all`, `--profile`, and sync's
whole-root listing); an explicit `--path`/`--folder` naming an excluded
name directly still works — a deliberate override, not a bug. Syncing
between two storages excludes a pattern configured on *either* side, so an
excluded directory present only on one side never turns into a surprising
deletion candidate under `--delete --apply`.

### Remote storages

SBESM has no SSH/network transport code. Mount a remote path with `sshfs`
(or anything else that presents as a normal local mount point) first, then
`init`/`register` that mount point exactly like a local disk. Two things to
expect: hashing (`index`/`verify`) over a network mount will be noticeably
slower and more latency-sensitive than on local disk, since every byte
streams over the network for each hash; and a FUSE-mounted path has no
block-device UUID, so identity checks fall back to a liveness probe instead.

## Troubleshooting

- **A file was silently corrupted (same size/mtime, different content)**:
  `index`'s fast path won't catch this (by design — it's a metadata-only
  shortcut). Run `verify`, which always re-hashes. If the mismatch is
  legitimate (you *meant* to change the file), run `accept --path <file>
  --apply` to update the reference once you've confirmed it.
- **`index`/`sync` reports a conflict**: never silently resolved. Inspect with
  `diff`, then either fix the file by hand or pass `--overwrite-conflicts`
  (sync) to accept source's version, or `accept --apply` (on the storage
  whose version you want to keep as the new reference).
- **A storage reports "ambiguous"** in `sbesm storages`: two registered
  entries share the same storage ID — almost always a cloned/imaged disk.
  Resolve by re-registering one of them under a distinct identity (or
  deciding which one is authoritative) before relying on either.
- **"not mounted or not responding"**: the root path isn't currently a live,
  responsive mount. Check the disk is actually connected before retrying.
- **A command is refused as "storage busy"**: another SBESM process (or an
  interrupted previous run that didn't exit) is holding the single-writer
  lock for that storage. Wait for it to finish, or confirm no process is
  stuck before manually removing `.sbesm/.lock`.

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | `SUCCESS` | Completed cleanly, nothing noteworthy |
| 1 | `FINDINGS` | Completed, but something worth your attention was reported (a mismatch, a conflict, a duplicate, destination-only files, …) |
| 2 | `USAGE_ERROR` | Invalid arguments, refused selection, or an unapproved conflict |
| 3 | `STORAGE_NOT_FOUND` | Unknown storage, identity mismatch, or ambiguous/cloned ID |
| 4 | `IO_FAILURE` | A read/write actually failed (disk full, permission denied, rsync error, locked database) |
| 5 | `INTERRUPTED` | The operation was interrupted (e.g. Ctrl-C) mid-run |
| 6 | `NOT_IMPLEMENTED` | Reserved for not-yet-built command stubs |

## Timestamp limitations

`reconcile` only ever aligns mtimes of files it has *proven* identical in
content — never based on a stale or conflicted reference. Filesystems have
different timestamp precision (ext4/btrfs ≈1ms, FAT/exFAT ≈2s, unknown/FUSE
mounts default to a conservative 2s), so a difference smaller than the
detected tolerance is treated as already-aligned rather than repeatedly
"fixed" every run. Override the auto-detected tolerance per storage with
`[sync] mtime_tolerance_ns` in `config.toml` if needed. `reconcile` never
touches `ctime` (the OS maintains it automatically on any metadata change,
including the `mtime` update itself) and preserves `atime`.
