#!/usr/bin/env python3
"""Read/write the project's Korean translation source files.

`translation/ko/<NNN>.txt`, `translation/names.tsv`, and
`translation/ui_strings.tsv` are the SOURCE OF TRUTH for the Korean script
and the only translation data this repository distributes. None of them
contain text from the original game -- each holds only an identifier
(dialogue id, raw character-name key, or UI string Key) and its Korean
translation. `translation/ko/<NNN>.txt` uses U+23CE (⏎) to mark an in-text
line break.

The working files under `work/` (which do carry the original Japanese and
English) are regenerated from a local game install by `ifalsus.py
extract-translations` / `extract-names` / `extract-ui-strings` and are
never committed.
"""
import json, os, re, sys

KO_DIR = "translation/ko"
BY_STORY = "work/translations/by_story"
NL = "⏎"
HEADER = (
    "# Korean translation source -- In Falsus\n"
    "# Format: <id><TAB><korean>, with U+23CE for an in-text line break.\n"
    "# The original Japanese lives in the game install; run\n"
    "#   ifalsus.py extract-translations && tools/dump_jp.py <NNN>\n"
    "# to read it alongside this file.\n"
)


def read_ko(sid):
    """-> {id: korean} for one story (empty dict if the file is absent)."""
    path = f"{KO_DIR}/{sid}.txt"
    if not os.path.exists(path):
        return {}
    ko = {}
    for ln, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\d{3}-\d{3})\t(.*)$", line)
        if not m:
            raise SystemExit(f"{path}:{ln}: bad line: {line[:60]!r}")
        k, v = m.group(1), m.group(2).replace(NL, "\n").strip()
        if k in ko:
            raise SystemExit(f"{path}:{ln}: duplicate id {k}")
        if "\\n" in v:
            raise SystemExit(f"{path}:{ln}: literal backslash-n in {k}")
        ko[k] = v
    return ko


def write_ko(sid, ko, order=None):
    """Write {id: korean} to translation/ko/<NNN>.txt, one entry per line."""
    os.makedirs(KO_DIR, exist_ok=True)
    ids = order or sorted(ko)
    with open(f"{KO_DIR}/{sid}.txt", "w", encoding="utf-8") as f:
        f.write(HEADER)
        for i in ids:
            if ko.get(i):
                f.write(f"{i}\t{ko[i].replace(chr(10), NL)}\n")


def story_ids(sid):
    """Entry ids of a story, in game order (needs the extracted work/ files)."""
    d = json.load(open(f"{BY_STORY}/{sid}.json"))
    return [e["Id"] for e in d["entries"]]


def all_stories():
    return sorted(
        f[:-5] for f in os.listdir(BY_STORY) if f.endswith(".json")
    )


NAMES_SRC = "translation/names.tsv"
NAMES_WORK = "work/names/names.json"
NAMES_HEADER = (
    "# Korean character names -- In Falsus\n"
    "# Format: <raw name><TAB><korean>. The raw name is the game's internal\n"
    "# key in DynamicStringMapping.rawStoryNameTypeMapping; only rows this\n"
    "# project translates are listed.\n"
)


def read_names():
    """-> {raw: korean}."""
    if not os.path.exists(NAMES_SRC):
        return {}
    out = {}
    for ln, raw in enumerate(open(NAMES_SRC, encoding="utf-8"), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" not in line:
            raise SystemExit(f"{NAMES_SRC}:{ln}: no TAB: {line[:40]!r}")
        k, v = line.split("\t", 1)
        out[k] = v.strip()
    return out


def write_names(names):
    with open(NAMES_SRC, "w", encoding="utf-8") as f:
        f.write(NAMES_HEADER)
        for k in sorted(names):
            if names[k]:
                f.write(f"{k}\t{names[k]}\n")


UI_STRINGS_SRC = "translation/ui_strings.tsv"
UI_STRINGS_WORK = "work/ui_strings/ui_strings.json"
UI_STRINGS_HEADER = (
    "# Korean UI strings -- In Falsus\n"
    "# Format: <Key><TAB><KeyName><TAB><korean>. Key is the integer\n"
    "# Str.Strings.Key enum value; KeyName is that enum member's name\n"
    "# (informational only -- pack-ui-strings matches by Key, never by name).\n"
    "# Only rows this project translates are listed; everything else keeps\n"
    "# its English text (format strings, judgment badges like EXACT/NEAR,\n"
    "# debug/unused entries, language self-names).\n"
)


def read_ui_strings():
    """-> {Key(int): korean}."""
    if not os.path.exists(UI_STRINGS_SRC):
        return {}
    out = {}
    for ln, raw in enumerate(open(UI_STRINGS_SRC, encoding="utf-8"), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise SystemExit(f"{UI_STRINGS_SRC}:{ln}: expected 3 TAB-separated fields: {line[:60]!r}")
        k, _name, v = parts
        if "\\n" in v:
            raise SystemExit(f"{UI_STRINGS_SRC}:{ln}: literal backslash-n in key {k}")
        out[int(k)] = v.replace(NL, "\n").strip()
    return out


def write_ui_strings(entries):
    """entries: iterable of {Key, KeyName, Korean}. In-text line breaks are
    encoded as U+23CE (⏎), same convention as translation/ko/<NNN>.txt."""
    os.makedirs(os.path.dirname(UI_STRINGS_SRC), exist_ok=True)
    rows = [e for e in entries if e.get("Korean", "").strip()]
    rows.sort(key=lambda e: e["Key"])
    with open(UI_STRINGS_SRC, "w", encoding="utf-8") as f:
        f.write(UI_STRINGS_HEADER)
        for e in rows:
            ko = e["Korean"].replace("\n", NL)
            f.write(f"{e['Key']}\t{e['KeyName']}\t{ko}\n")


def _id_table_header(kind, table_desc):
    return (
        f"# Korean {kind} -- In Falsus\n"
        "# Format: <Id><TAB><IdStr><TAB><korean>. Id is the integer key and\n"
        "# IdStr the human-readable key (e.g. \"1-1-a\", \"2-r-7\") in\n"
        f"# DynamicStringMapping.{table_desc} -- both informational, packing\n"
        "# matches by Id+IdStr together, never by Korean text.\n"
        "# Only rows this project translates are listed.\n"
    )


def _read_id_table(src):
    if not os.path.exists(src):
        return {}
    out = {}
    for ln, raw in enumerate(open(src, encoding="utf-8"), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise SystemExit(f"{src}:{ln}: expected 3 TAB-separated fields: {line[:60]!r}")
        i, idstr, v = parts
        if "\\n" in v:
            raise SystemExit(f"{src}:{ln}: literal backslash-n in id {i}")
        out[(int(i), idstr)] = v.replace(NL, "\n").strip()
    return out


def _write_id_table(src, header, entries):
    """entries: iterable of {Id, IdStr, Korean}."""
    os.makedirs(os.path.dirname(src), exist_ok=True)
    rows = [e for e in entries if e.get("Korean", "").strip()]
    rows.sort(key=lambda e: e["Id"])
    with open(src, "w", encoding="utf-8") as f:
        f.write(header)
        for e in rows:
            ko = e["Korean"].replace("\n", NL)
            f.write(f"{e['Id']}\t{e['IdStr']}\t{ko}\n")


CARD_NAMES_SRC = "translation/card_names.tsv"
CARD_NAMES_WORK = "work/names/card_names.json"
ENCOUNTER_NAMES_SRC = "translation/encounter_names.tsv"
ENCOUNTER_NAMES_WORK = "work/names/encounter_names.json"
RECIPE_NAMES_SRC = "translation/recipe_names.tsv"
RECIPE_NAMES_WORK = "work/names/recipe_names.json"


def read_card_names():
    return _read_id_table(CARD_NAMES_SRC)


def write_card_names(entries):
    _write_id_table(CARD_NAMES_SRC, _id_table_header("card names", "cardNameTypeMapping"), entries)


def read_encounter_names():
    return _read_id_table(ENCOUNTER_NAMES_SRC)


def write_encounter_names(entries):
    _write_id_table(ENCOUNTER_NAMES_SRC, _id_table_header("encounter/Reflect titles", "encounterIdTypeMapping"), entries)


def read_recipe_names():
    return _read_id_table(RECIPE_NAMES_SRC)


def write_recipe_names(entries):
    _write_id_table(RECIPE_NAMES_SRC, _id_table_header("recipe names", "recipeIdTypeMapping"), entries)


def export():
    """work/ JSON -> translation/ (one-time migration / re-derive committed
    files from work/). Returns a dict of counts. Callable directly (used by
    `ifalsus.py`) as well as from the CLI below."""
    n = 0
    for sid in all_stories():
        d = json.load(open(f"{BY_STORY}/{sid}.json"))
        ko = {e["Id"]: e.get("Korean", "") for e in d["entries"]}
        if any(ko.values()):
            write_ko(sid, ko, [e["Id"] for e in d["entries"]])
            n += 1
    d = json.load(open(NAMES_WORK))
    write_names({e["Raw"]: e.get("Korean", "") for e in d["entries"] if e["Raw"]})
    n_ui = 0
    if os.path.exists(UI_STRINGS_WORK):
        ui = json.load(open(UI_STRINGS_WORK))
        write_ui_strings(ui["entries"])
        n_ui = sum(1 for e in ui["entries"] if e.get("Korean", "").strip())
    n_cards = 0
    if os.path.exists(CARD_NAMES_WORK):
        cn = json.load(open(CARD_NAMES_WORK))
        write_card_names(cn["entries"])
        n_cards = sum(1 for e in cn["entries"] if e.get("Korean", "").strip())
    n_enc = 0
    if os.path.exists(ENCOUNTER_NAMES_WORK):
        en = json.load(open(ENCOUNTER_NAMES_WORK))
        write_encounter_names(en["entries"])
        n_enc = sum(1 for e in en["entries"] if e.get("Korean", "").strip())
    n_recipe = 0
    if os.path.exists(RECIPE_NAMES_WORK):
        rn = json.load(open(RECIPE_NAMES_WORK))
        write_recipe_names(rn["entries"])
        n_recipe = sum(1 for e in rn["entries"] if e.get("Korean", "").strip())
    return {"stories": n, "ui_strings": n_ui, "card_names": n_cards, "encounter_names": n_enc, "recipe_names": n_recipe}


def sync():
    """translation/ -> work/ JSON (before verify / pack, and right after a
    fresh `extract-*` so already-translated text shows up in work/). Returns
    a dict of counts. Callable directly (used by `ifalsus.py`) as well as
    from the CLI below."""
    tot = 0
    for sid in all_stories():
        ko = read_ko(sid)
        if not ko:
            continue
        p = f"{BY_STORY}/{sid}.json"
        d = json.load(open(p))
        for e in d["entries"]:
            if ko.get(e["Id"]):
                e["Korean"] = ko[e["Id"]]
                tot += 1
        json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
    names = read_names()
    tot_names = 0
    if names and os.path.exists(NAMES_WORK):
        d = json.load(open(NAMES_WORK))
        for e in d["entries"]:
            if names.get(e["Raw"]):
                e["Korean"] = names[e["Raw"]]
                tot_names += 1
        json.dump(d, open(NAMES_WORK, "w"), ensure_ascii=False, indent=1)
    ui = read_ui_strings()
    tot_ui = 0
    if ui and os.path.exists(UI_STRINGS_WORK):
        d = json.load(open(UI_STRINGS_WORK))
        for e in d["entries"]:
            if ui.get(e["Key"]):
                e["Korean"] = ui[e["Key"]]
                tot_ui += 1
        json.dump(d, open(UI_STRINGS_WORK, "w"), ensure_ascii=False, indent=1)
    cn = read_card_names()
    tot_cards = 0
    if cn and os.path.exists(CARD_NAMES_WORK):
        d = json.load(open(CARD_NAMES_WORK))
        for e in d["entries"]:
            if cn.get((e["Id"], e["IdStr"])):
                e["Korean"] = cn[(e["Id"], e["IdStr"])]
                tot_cards += 1
        json.dump(d, open(CARD_NAMES_WORK, "w"), ensure_ascii=False, indent=1)
    en = read_encounter_names()
    tot_enc = 0
    if en and os.path.exists(ENCOUNTER_NAMES_WORK):
        d = json.load(open(ENCOUNTER_NAMES_WORK))
        for e in d["entries"]:
            if en.get((e["Id"], e["IdStr"])):
                e["Korean"] = en[(e["Id"], e["IdStr"])]
                tot_enc += 1
        json.dump(d, open(ENCOUNTER_NAMES_WORK, "w"), ensure_ascii=False, indent=1)
    rn = read_recipe_names()
    tot_recipe = 0
    if rn and os.path.exists(RECIPE_NAMES_WORK):
        d = json.load(open(RECIPE_NAMES_WORK))
        for e in d["entries"]:
            if rn.get((e["Id"], e["IdStr"])):
                e["Korean"] = rn[(e["Id"], e["IdStr"])]
                tot_recipe += 1
        json.dump(d, open(RECIPE_NAMES_WORK, "w"), ensure_ascii=False, indent=1)
    return {"stories": tot, "names": tot_names, "ui_strings": tot_ui, "card_names": tot_cards, "encounter_names": tot_enc, "recipe_names": tot_recipe}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        c = export()
        print(
            f"exported {c['stories']} stories to {KO_DIR}/, names to {NAMES_SRC}, "
            f"{c['ui_strings']} UI strings to {UI_STRINGS_SRC}, {c['card_names']} card names to {CARD_NAMES_SRC}, "
            f"{c['encounter_names']} encounter names to {ENCOUNTER_NAMES_SRC}, {c['recipe_names']} recipe names to {RECIPE_NAMES_SRC}"
        )
    elif cmd == "sync":
        c = sync()
        print(
            f"synced {c['stories']} Korean lines into {BY_STORY}/, {c['names']} names, {c['ui_strings']} UI strings, "
            f"{c['card_names']} card names, {c['encounter_names']} encounter names, {c['recipe_names']} recipe names"
        )
    else:
        print(__doc__)
        print("usage: ko_io.py export|sync")
