#!/usr/bin/env python3
"""Merge a chunk of freshly translated lines into the project's Korean source.

Input: one entry per line, `<id><space or TAB><korean>`, U+23CE (KO) for an
in-text line break; `#` comments and blank lines ignored.

The lines are merged into `translation/ko/<NNN>.txt` (the committed source of
truth, rewritten in game order) and mirrored into the local working file
`work/translations/by_story/<NNN>.json` so `dump_jp.py --ko`, other QA
tooling, and `ifalsus.py verify` see them.

usage: apply_ko.py <NNN> <chunk.txt>
"""
import json, re, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ko_io import read_ko, write_ko, story_ids, NL, BY_STORY

sid, path = sys.argv[1], sys.argv[2]

new = {}
for ln, raw in enumerate(open(path, encoding="utf-8"), 1):
    line = raw.rstrip("\n")
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    m = re.match(r"^(\d{3}-\d{3})[ \t]+(.*)$", line)
    if not m:
        raise SystemExit(f"{path}:{ln}: bad line: {line[:60]!r}")
    k, v = m.group(1), m.group(2).replace(NL, "\n").strip()
    if k in new:
        raise SystemExit(f"{path}:{ln}: duplicate id {k}")
    if "\\n" in v:
        raise SystemExit(f"{path}:{ln}: literal backslash-n in {k}")
    new[k] = v

order = story_ids(sid)
unknown = [k for k in new if k not in set(order)]
if unknown:
    raise SystemExit(f"{path}: ids not in story {sid}: {unknown}")

ko = read_ko(sid)
ko.update(new)
write_ko(sid, ko, order)

p = f"{BY_STORY}/{sid}.json"
d = json.load(open(p))
for e in d["entries"]:
    e["Korean"] = ko.get(e["Id"], "")
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)

missing = [i for i in order if not ko.get(i)]
print(f"story {sid}: +{len(new)} lines, {len(order)-len(missing)}/{len(order)} filled")
if missing:
    print(f"  empty ({len(missing)}): {missing[:12]}{'...' if len(missing)>12 else ''}")
