#!/usr/bin/env python3
"""Repair malformed translation-mapping JSON files (stray quote artifacts).

Fixes lines like:  "035-135": \\"\\"\\"text\\"\\"\\",
by unescaping stray backslash-quotes, stripping quote-wrapping artifacts,
re-serializing with json.dumps, and normalizing literal '\\n' to real newlines.
Usage: fixjson.py <file.json> [more.json ...]
"""
import json, sys, re


def fix_file(path):
    raw = open(path, encoding="utf-8").read()
    out = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s or s in ("{", "}", "},"):
            out.append(line)
            continue
        m = re.match(r'^"([^"]+)":\s*(.*)$', s)
        if not m:
            out.append(line)
            continue
        key, val = m.group(1), m.group(2)
        if "\\" not in val and val.startswith('"') and val.endswith(("\"", "\",")):
            out.append(line)  # already clean
            continue
        v = val.rstrip(",").strip()
        v = v.replace('\\"', '"')
        v = v.replace("\\\\n", "\n").replace("\\n", "\n")
        v = v.replace('"', "")  # strip ALL quote artifacts from value
        v = v.replace("''", "'")
        out.append(json.dumps(key, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False) + ",")
    raw = "\n".join(out).rstrip()
    if raw.endswith(","):
        raw = raw[:-1]
    raw += "\n}\n"
    if not raw.lstrip().startswith("{"):
        raw = "{\n" + raw
    try:
        json.load(open(path)) if False else json.loads(raw)
    except Exception as e:
        raise SystemExit(f"could not auto-fix {path}: {e}")
    open(path, "w", encoding="utf-8").write(raw)
    print(f"fixed {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for p in sys.argv[1:]:
        fix_file(p)
