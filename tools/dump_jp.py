#!/usr/bin/env python3
"""Compact translator view of a story: id | speaker | JP (ruby stripped).

usage: dump_jp.py <NNN> [start] [end] [--ko] [--en]
  start/end are 0-based entry indices (end exclusive).
  --ko also prints the current Korean, --en the shipped English.
"""
import json, re, sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = {a for a in sys.argv[1:] if a.startswith("--")}
sid = args[0]
start = int(args[1]) if len(args) > 1 else 0
end = int(args[2]) if len(args) > 2 else 10**9

d = json.load(open(f"work/translations/by_story/{sid}.json"))
ents = d["entries"]
print(f"# story {sid}: {len(ents)} entries, showing {start}..{min(end,len(ents))}")
prev_script = None
for e in ents[start:end]:
    sc = e.get("Script", "")
    if sc and sc != prev_script:
        print(f"## script: {sc}")
        prev_script = sc
    jp = re.sub(r"<rt>.*?</rt>|</?ruby>", "", e["Japanese"]).replace("\n", "⏎")
    spk = e.get("SpeakerRaw", "") or "-"
    print(f"{e['Id']} [{spk}] {jp}")
    if "--en" in flags:
        print(f"   EN: {e['English']}".replace("\n", "⏎"))
    if "--ko" in flags and e.get("Korean"):
        print(f"   ko: {e['Korean']}".replace("\n", "⏎"))
