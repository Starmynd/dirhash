#!/usr/bin/env python3
"""dirhash - create and verify checksum manifests for directory trees.

create: record path, size and SHA-256 for every regular file into a JSONL
        manifest (sorted by path), followed by a {"_total": ...} line holding
        the SHA-256 of all record lines.
verify: recompute the tree and report ADDED / REMOVED / MODIFIED files.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys

CHUNK = 1 << 20


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(os.path.basename(rel), p)
               for p in patterns)


def scan_tree(root: str, patterns: list[str]) -> list[dict]:
    records = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fname in sorted(filenames):
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            if excluded(rel, patterns):
                continue
            size = os.path.getsize(full)
            records.append({"path": rel, "size": size, "sha256": sha256_file(full)})
    return records


def create(root: str, out: str, patterns: list[str]) -> str:
    records = scan_tree(root, patterns)
    total = hashlib.sha256()
    with open(out, "w", encoding="utf-8") as fh:
        for rec in records:
            line = json.dumps(rec, sort_keys=True)
            total.update(line.encode())
            fh.write(line + "\n")
        fh.write(json.dumps({"_total": total.hexdigest()}) + "\n")
    return total.hexdigest()


def read_manifest(manifest: str) -> tuple[dict[str, dict], str]:
    records: dict[str, dict] = {}
    total = ""
    with open(manifest, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "_total" in obj:
                total = obj["_total"]
            else:
                records[obj["path"]] = obj
    return records, total


def verify(root: str, manifest: str, patterns: list[str]) -> tuple[bool, list[str]]:
    old, expected_total = read_manifest(manifest)
    new_list = scan_tree(root, patterns)
    new = {r["path"]: r for r in new_list}
    total = hashlib.sha256()
    for r in new_list:
        total.update(json.dumps(r, sort_keys=True).encode())

    entries: list[tuple[str, str]] = []  # (path, label)
    for path in set(old) - set(new):
        entries.append((path, "REMOVED"))
    for path in set(new) - set(old):
        entries.append((path, "ADDED"))
    for path in set(new) & set(old):
        if new[path]["sha256"] != old[path]["sha256"] or \
           new[path]["size"] != old[path]["size"]:
            entries.append((path, "MODIFIED"))
    entries.sort()
    problems = [f"{label} {path}" for path, label in entries]
    if expected_total and total.hexdigest() != expected_total and not problems:
        problems.append("MODIFIED <manifest total mismatch>")
    return (not problems), problems


def _selftest() -> int:
    import tempfile

    failed = 0

    def check(cond: bool, label: str) -> None:
        nonlocal failed
        print(("PASS " if cond else "FAIL ") + label)
        if not cond:
            failed += 1

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "tree")
        os.makedirs(os.path.join(root, "sub"))
        paths = {
            "a.txt": b"alpha",
            "sub/b.txt": b"bravo",
        }
        for rel, data in paths.items():
            with open(os.path.join(root, rel), "wb") as fh:
                fh.write(data)

        manifest = os.path.join(tmp, "m.jsonl")
        t1 = create(root, manifest, [])
        ok, probs = verify(root, manifest, [])
        check(ok and t1, "clean verify passes")

        with open(os.path.join(root, "a.txt"), "wb") as fh:
            fh.write(b"ALPHA-CHANGED")
        ok, probs = verify(root, manifest, [])
        check(not ok, "modification detected")
        check(probs == ["MODIFIED a.txt"], f"exact report (got {probs})")

        with open(os.path.join(root, "new.txt"), "wb") as fh:
            fh.write(b"new")
        os.remove(os.path.join(root, "sub/b.txt"))
        ok, probs = verify(root, manifest, [])
        check(not ok, "mixed changes detected")
        check(probs == ["MODIFIED a.txt", "ADDED new.txt", "REMOVED sub/b.txt"],
              f"sorted report (got {probs})")

        m2 = os.path.join(tmp, "m2.jsonl")
        create(root, m2, ["new.txt"])
        ok, probs = verify(os.path.join(root), m2, ["new.txt"])
        check(ok, "exclusion honored")

    print(f"selftest: failures={failed}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--test" in argv:
        return _selftest()

    ap = argparse.ArgumentParser(prog="dirhash",
                                 description="Create and verify checksum manifests.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="create a manifest for a directory")
    p_create.add_argument("dir")
    p_create.add_argument("-o", "--out", required=True, help="manifest path (.jsonl)")
    p_create.add_argument("--exclude", action="append", default=[],
                          metavar="PATTERN", help="fnmatch pattern (repeatable)")

    p_verify = sub.add_parser("verify", help="verify a directory against a manifest")
    p_verify.add_argument("dir")
    p_verify.add_argument("-m", "--manifest", required=True)
    p_verify.add_argument("--exclude", action="append", default=[],
                          metavar="PATTERN", help="fnmatch pattern (repeatable)")

    args = ap.parse_args(argv)

    if args.cmd == "create":
        total = create(args.dir, args.out, args.exclude)
        n = sum(1 for _ in open(args.out, encoding="utf-8")) - 1
        print(f"manifest written: {args.out} ({n} files, total {total[:16]}...)")
        return 0

    ok, problems = verify(args.dir, args.manifest, args.exclude)
    if problems:
        for p in problems:
            print(p)
        print(f"VERIFY FAILED: {len(problems)} difference(s)")
        return 1
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
