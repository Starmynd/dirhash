# dirhash

Create and verify checksum manifests for directory trees. Detect exactly what
changed - added, removed or modified - with per-file SHA-256. One file,
standard library only.

Use it to snapshot data directories before migrations, verify backups, or
detect drift between a shipped tree and a reference copy.

## Manifest format

JSONL, one record per file sorted by path, plus a final integrity line:

```json
{"path": "a.txt", "size": 5, "sha256": "aa10b..."}
{"path": "sub/b.txt", "size": 5, "sha256": "4ab2f..."}
{"_total": "9f86d0..."}
```

`_total` is the SHA-256 of all record lines: a single value you can compare
across hosts to see if the whole tree matches.

## Usage

```console
$ dirhash create ./data -o data.jsonl --exclude "*.log" --exclude ".git/*"
manifest written: data.jsonl (128 files, total 9f86d081...a)

$ dirhash verify ./data -m data.jsonl
MODIFIED config/app.conf
ADDED uploads/new-file.bin
VERIFY FAILED: 2 difference(s)

$ dirhash verify ./backup -m data.jsonl
VERIFY OK

$ dirhash --test
selftest: failures=0
```

Exit codes: `0` verify clean, `1` differences found.

## Notes

- Paths are stored POSIX-style and relative to the scanned root.
- Symlinks are skipped.
- `--exclude` patterns match the relative path or the file name (fnmatch).

## Testing

```console
$ python3 dirhash.py --test
```

Covers clean verification, exact modification/addition/removal reports,
report ordering and exclusion patterns.

## License

MIT
