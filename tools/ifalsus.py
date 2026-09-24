#!/usr/bin/env python3
"""ifalsus.py - In Falsus localization extraction / packing tool.

Converts the game's native asset formats (encrypted SAM script files,
Unity AssetBundle-embedded translation tables, embedded fonts) into plain
JSON / text files that are easy to translate, and packs edited files back
into the native formats without breaking the game.

Requires: Python 3.9+, UnityPy (see requirements.txt)

Usage:
    python3 ifalsus.py <command> [options]

Run `python3 ifalsus.py --help` for the command list, and
`python3 ifalsus.py <command> --help` for per-command options.

See README.md for full documentation of the game's data model.
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import time

try:
    import UnityPy
except ImportError:
    print("error: UnityPy is required. Install with: pip install UnityPy", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Addressable asset addresses (stable for this game's build).
ADDR_STORY_TRANSLATION_DETAILS = "Assets/BuildSpecificAssets/release/StoryTranslationDetails.asset"
ADDR_DYNAMIC_STRING_MAPPING = "Assets/BuildSpecificAssets/release/DynamicStringMapping.asset"
ADDR_STREAMING_ASSETS_MAPPING = "Assets/BuildSpecificAssets/release/StreamingAssetsMapping.asset"

# 8-byte repeating XOR key used by the game's "SAM" transform on script files
# (.sps/.spp/.spi). Derived from the shipped encrypted scripts.
SAM_XOR_KEY = bytes([0xF0, 0x16, 0x28, 0x4B, 0x7D, 0x9E, 0xC3, 0xA5])

SCRIPT_EXTS = (".sps", ".spp", ".spi")
FONT_SCRIPT_NAMES = ("FastTextFontFamily", "FastTextAsset")

# FastTextAsset slots inside a font family are indexed by FastTextStyle:
# 0=Regular, 1=Bold, 2=Italic(unused; faux italic), 3=Light, 4=Medium, 5=SemiBold
FONT_STYLE_SLOTS = ["Regular", "Bold", "Italic", "Light", "Medium", "SemiBold"]

# Fields of StoryTranslationDetails.StringMapping / DynamicStringMapping values.
TEXT_FIELDS = ["English", "Japanese", "Korean", "ChineseTC", "ChineseSC"]

# UI chrome strings: Str.StringsMapping ScriptableObject, loaded at runtime via
# Resources.Load("StringsMapping"). Lives in infalsus_Data/resources.assets,
# NOT in the Addressables bundle system, and unlike the addressable bundles
# this file carries no embedded Unity typetree (standard for IL2CPP main-data
# files) -- UnityPy needs IL2CPP type info to read/write it. See README.md
# "UI strings (StringsMapping)" for the one-time setup this requires.
UI_STRINGS_DATA_FILE = "resources.assets"
UI_STRINGS_SIBLING_FILE = "globalgamemanagers.assets"  # holds the MonoScript; must sit alongside resources.assets when UnityPy resolves the PPtr
UI_STRINGS_PATH_ID = 1394
UI_STRINGS_SCRIPT_NAME = "StringsMapping"
UI_STRINGS_FIELDS = ["English", "Japanese", "Korean", "TraditionalChinese", "SimplifiedChinese"]
UNITY_ENGINE_VERSION = "6000.3.9f1"  # this game's build; see README §4.7

GAME_DATA_DIRNAME = "infalsus_Data"

# Candidate Steam library roots for auto-detection (WSL/Windows/macOS/Linux).
GAME_SEARCH_GLOBS = [
    "/mnt/*/SteamLibrary/steamapps/common/*",
    "/mnt/*/steamapps/common/*",
    "/mnt/*/Program Files (x86)/Steam/steamapps/common/*",
    "/mnt/*/Games/SteamLibrary/steamapps/common/*",
    "/mnt/c/Program Files (x86)/Steam/steamapps/common/*",
    "*/SteamLibrary/steamapps/common/*",
    "*/steamapps/common/*",
    os.path.expanduser("~/.steam/steam/steamapps/common/*"),
    os.path.expanduser("~/SteamLibrary/steamapps/common/*"),
    os.path.expanduser("~/.local/share/Steam/steamapps/common/*"),
    "/Volumes/*/SteamLibrary/steamapps/common/*",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def sam_xor(data: bytes) -> bytes:
    """Apply (encrypt or decrypt) the repeating 8-byte XOR key."""
    klen = len(SAM_XOR_KEY)
    return bytes(b ^ SAM_XOR_KEY[i % klen] for i, b in enumerate(data))


def sniff_font_ext(data: bytes) -> str:
    if data[:4] == b"OTTO":
        return ".otf"
    if data[:4] in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
        return ".ttf"
    return ".bin"


def is_valid_font(data: bytes) -> bool:
    return sniff_font_ext(data) != ".bin"


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def commit_or_dry(args, game, bundle_fn, describe, env):
    """Write the packed bundle into the patch output directory (never the
    game dir), honoring --dry-run. `env` is the UnityPy environment holding
    the in-memory edits to be written.

    The game's current file is still backed up (once) so `restore` can undo
    an applied patch."""
    out_path = game.bundle_patch_path(bundle_fn)
    if getattr(args, "dry_run", False):
        log(f"[dry-run] would pack {describe} -> {out_path}")
        return False
    game_path = os.path.join(game.bundles_dir, bundle_fn)
    if os.path.exists(game_path):
        backup_file(game, game_path, os.path.join("bundles", bundle_fn))
    data = env.file.save(packer="original")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    atomic_write_bytes(out_path, data)
    log(f"packed {describe} -> {out_path}")
    return True


def backup_file(game, src_path, relname):
    """Copy src_path into backups/ (once). Returns backup path."""
    dst = os.path.join(game.workspace, "backups", relname)
    if os.path.exists(dst):
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src_path, dst)
    log(f"  backup: {src_path} -> {dst}")
    return dst


def atomic_write_bytes(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Game discovery
# ---------------------------------------------------------------------------


class Game:
    def __init__(self, game_path, workspace):
        self.path = os.path.abspath(game_path)
        self.workspace = os.path.abspath(workspace)
        self.patch_dir = os.path.join(self.workspace, "patch")
        data_dir = os.path.join(self.path, GAME_DATA_DIRNAME)
        if not os.path.isdir(data_dir):
            raise SystemExit(f"error: {self.path} does not contain {GAME_DATA_DIRNAME}")
        self.data_dir = data_dir
        self.streaming_assets = os.path.join(data_dir, "StreamingAssets")
        self.sam_dir = os.path.join(self.streaming_assets, "sam")
        self.bundles_dir = self._find_bundles_dir()

    def bundle_patch_path(self, bundle_fn):
        """Where `commit_or_dry` writes a packed copy of `bundle_fn`."""
        return os.path.join(
            self.patch_dir, GAME_DATA_DIRNAME, "StreamingAssets", "aa",
            os.path.basename(self.bundles_dir), bundle_fn,
        )

    def bundle_source_path(self, bundle_fn, prefer_patch=False):
        """Path to load `bundle_fn` from: an already-packed copy in `patch/`
        (if one exists and `prefer_patch`), else the live game install.

        This is what lets multiple `pack-*` commands touching the same
        bundle compose in a single `repack` run instead of each one
        clobbering the last, since every pack step would otherwise reload
        the untouched original from the game dir."""
        if prefer_patch:
            patched = self.bundle_patch_path(bundle_fn)
            if os.path.exists(patched):
                return patched
        return os.path.join(self.bundles_dir, bundle_fn)

    @classmethod
    def autodetect(cls, workspace, override=None):
        candidates = []
        if override:
            candidates.append(override)
        env_path = os.environ.get("INFALSUS_GAME_PATH")
        if env_path:
            candidates.append(env_path)
        for pat in GAME_SEARCH_GLOBS:
            for cand in sorted(glob.glob(pat)):
                if os.path.isdir(os.path.join(cand, GAME_DATA_DIRNAME)):
                    candidates.append(cand)
        for cand in candidates:
            if cand and os.path.isdir(os.path.join(cand, GAME_DATA_DIRNAME)):
                return cls(cand, workspace)
        raise SystemExit(
            "error: could not locate the In Falsus game directory.\n"
            "Pass --game-path <path to the folder containing infalsus_Data>,\n"
            "or set the INFALSUS_GAME_PATH environment variable."
        )

    def _find_bundles_dir(self):
        aa = os.path.join(self.streaming_assets, "aa")
        best = None
        for entry in sorted(os.listdir(aa)):
            sub = os.path.join(aa, entry)
            if not os.path.isdir(sub):
                continue
            if any(f.endswith(".bundle") for f in os.listdir(sub)):
                if best is None:
                    best = sub
                else:
                    raise SystemExit(
                        f"error: multiple bundle directories under {aa}; "
                        "this tool currently supports a single target platform."
                    )
        if best is None:
            raise SystemExit(f"error: no *.bundle files found under {aa}")
        return best

    # -- bundle index ------------------------------------------------------

    @property
    def index_path(self):
        return os.path.join(self.workspace, "work", "bundle_index.json")

    def build_index(self, force=False):
        """One pass over all bundles, recording containers, MonoScripts,
        inner serialized-file names, and MonoBehaviour m_Script/m_Name pairs.
        Incremental: the cache is rewritten periodically and already-indexed
        bundles are skipped on resume."""
        if os.path.exists(self.index_path) and not force:
            return read_json(self.index_path)
        index = {} if force else (read_json(self.index_path) if os.path.exists(self.index_path) else {})
        log(f"indexing bundles in {self.bundles_dir} (one-time, cached)...")
        files = sorted(
            f for f in os.listdir(self.bundles_dir) if f.endswith(".bundle") and f not in index
        )
        t0 = time.time()
        for i, fn in enumerate(files):
            rec = {
                "containers": [],
                "scripts": [],      # [(name, path_id)] MonoScripts
                "cab_names": [],    # inner serialized file names
                "monos": [],        # [(script_fileID, script_pathID, m_Name)]
            }
            try:
                env = UnityPy.load(os.path.join(self.bundles_dir, fn))
                for obj in env.objects:
                    if obj.type.name == "MonoScript":
                        try:
                            rec["scripts"].append([obj.read().m_Name, obj.path_id])
                        except Exception:
                            pass
                    elif obj.type.name == "MonoBehaviour":
                        try:
                            d = obj.read()
                            rec["monos"].append(
                                [d.m_Script.m_FileID, d.m_Script.m_PathID, getattr(d, "m_Name", "") or ""]
                            )
                        except Exception:
                            pass
                rec["containers"] = sorted(env.container.keys())
                for sf in env.file.files.values() if hasattr(env.file, "files") else []:
                    rec["cab_names"].append(sf.name)
            except Exception as e:
                rec["error"] = str(e)
            index[fn] = rec
            if (i + 1) % 25 == 0:
                write_json(self.index_path, index)
                log(f"  {i + 1}/{len(files)} ({time.time() - t0:.0f}s)")
        write_json(self.index_path, index)
        log(f"indexed {len(files)} bundles in {time.time() - t0:.0f}s -> {self.index_path}")
        return index

    def load_index(self):
        if not os.path.exists(self.index_path):
            log("bundle index missing; building it now...")
            return self.build_index()
        return read_json(self.index_path)

    def find_bundle_by_address(self, address, index=None):
        index = index or self.load_index()
        for fn, rec in index.items():
            if address in rec.get("containers", []):
                return fn
        raise SystemExit(f"error: no bundle contains address {address!r} (run `index`)")

    def find_font_bundle(self, index=None):
        """Locate the bundle holding FastTextFontFamily/FastTextAsset
        ScriptableObjects via MonoScript cross-references, then validate it
        by checking that its MonoBehaviours carry the font-family typetree."""
        index = index or self.load_index()
        # 1. path_ids of the FastTextFontFamily / FastTextAsset MonoScripts
        script_pids = set()
        for fn, rec in index.items():
            for name, pid in rec.get("scripts", []):
                if name in FONT_SCRIPT_NAMES:
                    script_pids.add(pid)
        if not script_pids:
            raise SystemExit("error: FastText MonoScripts not found in any bundle")
        # 2. candidate bundles: contain MonoBehaviours pointing at those scripts
        candidates = []
        for fn, rec in index.items():
            if any(pid in script_pids for _fid, pid, _name in rec.get("monos", [])):
                candidates.append(fn)
        # 3. validate via typetree (font families have a "fontAssets" list)
        for fn in candidates:
            env = UnityPy.load(os.path.join(self.bundles_dir, fn))
            for obj in env.objects:
                if obj.type.name != "MonoBehaviour":
                    continue
                try:
                    tt = obj.read_typetree()
                except Exception:
                    continue
                if "fontAssets" in tt:
                    return fn
        raise SystemExit("error: no font bundle found (bundles with FastText scripts had no fontAssets)")

    def load_mono_in_bundle(self, bundle_fn, typetree=True):
        """Yield (obj, typetree-or-None) for each MonoBehaviour in a bundle."""
        env = UnityPy.load(os.path.join(self.bundles_dir, bundle_fn))
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            if typetree:
                try:
                    yield obj, obj.read_typetree()
                except Exception:
                    yield obj, None
            else:
                yield obj, None

    def save_bundle(self, bundle_fn, env=None, out_path=None):
        """Serialize a (possibly modified) UnityPy bundle environment to bytes
        and write them to out_path. Never writes to the game dir unless an
        explicit out_path inside it is provided."""
        if env is None:
            env = UnityPy.load(os.path.join(self.bundles_dir, bundle_fn))
        data = env.file.save(packer="original")
        if out_path is None:
            raise ValueError("save_bundle requires an explicit out_path")
        atomic_write_bytes(out_path, data)
        return out_path


# ---------------------------------------------------------------------------
# Common pack helpers
# ---------------------------------------------------------------------------


def load_asset_by_address(game, address, index=None, prefer_patch=False):
    """`prefer_patch=True` (used by pack-* commands) loads an already-packed
    copy from `patch/` if one exists, so a later pack step builds on an
    earlier one instead of reloading the untouched original and clobbering
    it. Extract commands always pass the default (read the live game)."""
    fn = game.find_bundle_by_address(address, index)
    env = UnityPy.load(game.bundle_source_path(fn, prefer_patch=prefer_patch))
    monos = [o for o in env.objects if o.type.name == "MonoBehaviour"]
    if len(monos) != 1:
        raise SystemExit(f"error: expected exactly 1 MonoBehaviour in {fn}, got {len(monos)}")
    return fn, env, monos[0], monos[0].read_typetree()


def locale_map_entries(entries, src_field, dst_field, keep_dst_fallback=True):
    """Copy src_field -> dst_field for each entry dict where src is non-empty.
    Returns number of entries changed."""
    changed = 0
    for e in entries:
        src = (e.get(src_field) or "").strip()
        if src:
            e[dst_field] = src
            changed += 1
        elif not keep_dst_fallback:
            e[dst_field] = ""
    return changed


# ---------------------------------------------------------------------------
# Commands: locate / index
# ---------------------------------------------------------------------------


def cmd_locate(args, game):
    print(f"game path:        {game.path}")
    print(f"data dir:         {game.data_dir}")
    print(f"bundles dir:      {game.bundles_dir}")
    print(f"sam dir:          {game.sam_dir}")
    print(f"patch output:     {game.patch_dir}")
    print(f"workspace:        {game.workspace}")
    n_bundles = len([f for f in os.listdir(game.bundles_dir) if f.endswith(".bundle")])
    print(f"bundles:          {n_bundles}")
    if os.path.isdir(game.sam_dir):
        n_sam = len(os.listdir(game.sam_dir))
        print(f"sam files:        {n_sam}")
    for label, addr in [
        ("StoryTranslationDetails", ADDR_STORY_TRANSLATION_DETAILS),
        ("DynamicStringMapping", ADDR_DYNAMIC_STRING_MAPPING),
        ("StreamingAssetsMapping", ADDR_STREAMING_ASSETS_MAPPING),
    ]:
        if not os.path.exists(game.index_path):
            print(f"{label:<26} -> run `index` first")
            continue
        try:
            fn = game.find_bundle_by_address(addr)
            print(f"{label:<26} -> {fn}")
        except SystemExit:
            print(f"{label:<26} -> NOT FOUND")


def cmd_index(args, game):
    game.build_index(force=args.refresh)


# ---------------------------------------------------------------------------
# Commands: scripts (SAM)
# ---------------------------------------------------------------------------


def load_sam_mapping(game, index=None):
    fn, _env, _obj, tt = load_asset_by_address(game, ADDR_STREAMING_ASSETS_MAPPING, index)
    entries = tt["Entries"]
    return {e["FullLookupPath"]: e["Guid"] for e in entries}, fn


def cmd_extract_scripts(args, game):
    index = game.load_index()
    mapping, _ = load_sam_mapping(game, index)
    out_dir = os.path.join(game.workspace, "work", "scripts")
    os.makedirs(out_dir, exist_ok=True)
    write_json(os.path.join(out_dir, "sam_mapping.json"), mapping)
    script_files = {g: p for p, g in mapping.items() if p.lower().endswith(SCRIPT_EXTS)}
    log(f"script files in mapping: {len(script_files)}")
    missing = 0
    for guid, path in sorted(script_files.items(), key=lambda kv: kv[1]):
        src = os.path.join(game.sam_dir, guid)
        if not os.path.exists(src):
            missing += 1
            log(f"  MISSING on disk: {path} ({guid})")
            continue
        data = open(src, "rb").read()
        dec = sam_xor(data)
        dst = os.path.join(out_dir, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(dec.decode("utf-8", "replace"))
    log(f"extracted scripts -> {out_dir} (missing: {missing})")


def cmd_pack_scripts(args, game):
    mapping, _ = load_sam_mapping(game)
    scripts_dir = os.path.join(game.workspace, "work", "scripts")
    if not os.path.isdir(scripts_dir):
        raise SystemExit("error: no extracted scripts; run `extract-scripts` first")
    out_dir = os.path.join(game.patch_dir, GAME_DATA_DIRNAME, "StreamingAssets", "sam")
    n = 0
    for path, guid in mapping.items():
        if not path.lower().endswith(SCRIPT_EXTS):
            continue
        src = os.path.join(scripts_dir, path)
        if not os.path.exists(src):
            continue
        # only pack files whose content differs from the game's current copy
        game_src = os.path.join(game.sam_dir, guid)
        if os.path.exists(game_src):
            if sam_xor(open(game_src, "rb").read()) == open(src, "rb").read():
                continue
        if os.path.exists(game_src):
            backup_file(game, game_src, os.path.join("sam", guid))
        data = sam_xor(open(src, "rb").read())
        atomic_write_bytes(os.path.join(out_dir, guid), data)
        n += 1
    log(f"packed {n} changed script files -> {out_dir}")


def parse_script_speakers(text, alias_to_name):
    """Parse a decrypted .sps/.spp text; return {line_id: {alias, raw, order}}."""
    speakers = {}
    order = 0
    cur_id = None
    for ln in text.splitlines():
        ls = ln.strip()
        m = re.match(r"^id\s+([0-9A-Za-z_.-]+)\s*$", ls)
        if m:
            cur_id = m.group(1)
            continue
        sm = re.match(r"^(?:s|phone message \w+)\s+(\$[A-Za-z0-9_]+)\s*`", ls)
        if sm and cur_id:
            alias = sm.group(1)
            speakers[cur_id] = {
                "alias": alias,
                "raw": alias_to_name.get(alias, alias),
                "order": order,
            }
            order += 1
    return speakers


def cmd_extract_context(args, game):
    """Build the translator-facing per-story files: dialogue entries merged
    with speaker info from the decrypted scripts."""
    scripts_dir = os.path.join(game.workspace, "work", "scripts")
    trans_dir = os.path.join(game.workspace, "work", "translations")
    if not os.path.isdir(scripts_dir):
        raise SystemExit("error: run `extract-scripts` first")
    if not os.path.isdir(trans_dir):
        raise SystemExit("error: run `extract-translations` first")
    # alias table from names.spp
    names_path = os.path.join(scripts_dir, "assets", "scripts", "names.spp")
    alias_to_name = {}
    if os.path.exists(names_path):
        for ln in open(names_path, encoding="utf-8"):
            m = re.match(r'^alias\s+(\$[A-Za-z0-9_]+)\s+"(.*)"\s*$', ln.strip())
            if m:
                alias_to_name[m.group(1)] = m.group(2)
    # collect id -> (speaker, script) across all scripts
    id_speaker = {}
    id_script = {}
    for root, _dirs, files in os.walk(scripts_dir):
        for fn in sorted(files):
            if not fn.endswith((".sps", ".spi", ".spp")):
                continue
            path = os.path.relpath(os.path.join(root, fn), scripts_dir)
            if fn.endswith(".spp"):
                continue
            text = open(os.path.join(root, fn), encoding="utf-8").read()
            for lid, info in parse_script_speakers(text, alias_to_name).items():
                id_speaker[lid] = info
                id_script[lid] = path
    # merge into per-story files
    by_story = {}
    for fn in sorted(os.listdir(os.path.join(trans_dir, "by_story"))):
        if not fn.endswith(".json"):
            continue
        story = fn[:-5]
        data = read_json(os.path.join(trans_dir, "by_story", fn))
        for e in data["entries"]:
            lid = e["Id"]
            e["SpeakerRaw"] = id_speaker.get(lid, {}).get("raw", "")
            e["SpeakerAlias"] = id_speaker.get(lid, {}).get("alias", "")
            e["Script"] = id_script.get(lid, "")
        by_story[story] = data
        write_json(os.path.join(trans_dir, "by_story", fn), data)
    log(f"merged speaker context into {len(by_story)} story files")


# ---------------------------------------------------------------------------
# Commands: translations (StoryTranslationDetails)
# ---------------------------------------------------------------------------


def cmd_extract_translations(args, game):
    index = game.load_index()
    fn, _env, _obj, tt = load_asset_by_address(game, ADDR_STORY_TRANSLATION_DETAILS, index)
    translations = tt["Translations"]
    out_dir = os.path.join(game.workspace, "work", "translations")
    by_story_dir = os.path.join(out_dir, "by_story")
    os.makedirs(by_story_dir, exist_ok=True)
    stories = {}
    for e in translations:
        story = e["Id"].split("-")[0]
        stories.setdefault(story, []).append(
            {"Id": e["Id"], **{f: e[f] for f in TEXT_FIELDS}}
        )
    for story, entries in sorted(stories.items()):
        write_json(os.path.join(by_story_dir, f"{story}.json"), {"story": story, "entries": entries})
    write_json(os.path.join(out_dir, "story_translations.json"), {"Translations": translations})
    # TSV view
    tsv_path = os.path.join(out_dir, "story_translations.tsv")
    with open(tsv_path, "w", encoding="utf-8", newline="") as f:
        f.write("Id\tJapanese\tEnglish\tKorean\n")
        for e in translations:
            f.write(
                e["Id"]
                + "\t"
                + e["Japanese"].replace("\t", " ").replace("\n", "\\n")
                + "\t"
                + e["English"].replace("\t", " ").replace("\n", "\\n")
                + "\t"
                + e["Korean"].replace("\t", " ").replace("\n", "\\n")
                + "\n"
            )
    log(f"extracted {len(translations)} entries across {len(stories)} stories -> {out_dir}")
    log(f"bundle: {fn}")


def cmd_pack_translations(args, game):
    trans_dir = os.path.join(game.workspace, "work", "translations")
    by_story_dir = os.path.join(trans_dir, "by_story")
    if not os.path.isdir(by_story_dir):
        raise SystemExit("error: run `extract-translations` first")
    index = game.load_index()
    fn, env, obj, tt = load_asset_by_address(game, ADDR_STORY_TRANSLATION_DETAILS, index, prefer_patch=True)
    current = tt["Translations"]
    current_by_id = {e["Id"]: e for e in current}
    # load edits from by_story files
    edits = {}
    for f in sorted(os.listdir(by_story_dir)):
        if not f.endswith(".json"):
            continue
        data = read_json(os.path.join(by_story_dir, f))
        for e in data["entries"]:
            if e["Id"] in edits:
                raise SystemExit(f"error: duplicate id {e['Id']} in {f}")
            edits[e["Id"]] = e
    # validate coverage: every current id must be present in edits
    missing = [i for i in current_by_id if i not in edits]
    if missing and not args.allow_partial:
        raise SystemExit(
            f"error: {len(missing)} ids missing from edited files "
            f"(e.g. {missing[:5]}). Re-run `extract-translations` + `extract-context`, "
            "or pass --allow-partial."
        )
    src_field, dst_field = args.locale_map.split("->")
    if src_field not in TEXT_FIELDS or dst_field not in TEXT_FIELDS:
        raise SystemExit(f"error: --locale-map fields must be among {TEXT_FIELDS}")
    changed = 0
    for e in current:
        src = (edits.get(e["Id"], {}).get(src_field) or "").strip()
        if src:
            e[dst_field] = src
            changed += 1
    log(f"applied {changed}/{len(current)} entries ({src_field} -> {dst_field})")
    if changed == 0:
        log("nothing to pack (no non-empty source fields); skipping")
        return
    if args.dry_run:
        log("[dry-run] bundle would be written (skipped)")
        return
    obj.save_typetree(tt)
    commit_or_dry(args, game, fn, "StoryTranslationDetails", env)


# ---------------------------------------------------------------------------
# Commands: names (DynamicStringMapping)
# ---------------------------------------------------------------------------


def cmd_extract_names(args, game):
    index = game.load_index()
    fn, _env, _obj, tt = load_asset_by_address(game, ADDR_DYNAMIC_STRING_MAPPING, index)
    m = tt["rawStoryNameTypeMapping"]
    ids = m["Ids"]
    vals = m["IdValues"]
    if len(ids) != len(vals):
        raise SystemExit("error: Ids/IdValues length mismatch in DynamicStringMapping")
    out_dir = os.path.join(game.workspace, "work", "names")
    entries = []
    for i, (idv, val) in enumerate(zip(ids, vals)):
        entries.append(
            {
                "Raw": idv.get("Value", ""),
                "English": val.get("English", ""),
                "Japanese": val.get("Japanese", ""),
                "Korean": val.get("Korean", ""),
                "TraditionalChinese": val.get("TraditionalChinese", ""),
                "SimplifiedChinese": val.get("SimplifiedChinese", ""),
            }
        )
    write_json(os.path.join(out_dir, "names.json"), {"entries": entries})
    log(f"extracted {len(entries)} name entries -> {out_dir}/names.json")
    log(f"bundle: {fn}")


def cmd_pack_names(args, game):
    names_path = os.path.join(game.workspace, "work", "names", "names.json")
    if not os.path.exists(names_path):
        raise SystemExit("error: run `extract-names` first")
    data = read_json(names_path)
    index = game.load_index()
    fn, env, obj, tt = load_asset_by_address(game, ADDR_DYNAMIC_STRING_MAPPING, index, prefer_patch=True)
    m = tt["rawStoryNameTypeMapping"]
    ids = m["Ids"]
    vals = m["IdValues"]
    entries = data["entries"]
    if len(entries) != len(ids):
        raise SystemExit(
            f"error: entry count mismatch (json={len(entries)} asset={len(ids)}); "
            "do not add/remove entries, edit fields only."
        )
    for i, e in enumerate(entries):
        if e["Raw"] != ids[i].get("Value", ""):
            raise SystemExit(
                f"error: entry {i} raw name mismatch ({e['Raw']!r} != {ids[i].get('Value','')!r}); "
                "order must match the extracted file."
            )
    src_field, dst_field = args.locale_map.split("->")
    field_to_key = {
        "English": "English",
        "Japanese": "Japanese",
        "Korean": "Korean",
        "ChineseTC": "TraditionalChinese",
        "ChineseSC": "SimplifiedChinese",
    }
    if src_field not in field_to_key or dst_field not in field_to_key:
        raise SystemExit(f"error: --locale-map fields must be among {TEXT_FIELDS}")
    changed = 0
    for i, e in enumerate(entries):
        src = (e.get(src_field) or "").strip()
        if src:
            vals[i][field_to_key[dst_field]] = src
            changed += 1
    log(f"applied {changed}/{len(entries)} name entries ({src_field} -> {dst_field})")
    if changed == 0:
        log("nothing to pack (no non-empty source fields); skipping")
        return
    if args.dry_run:
        log("[dry-run] bundle would be written (skipped)")
        return
    obj.save_typetree(tt)
    commit_or_dry(args, game, fn, "DynamicStringMapping", env)


# ---------------------------------------------------------------------------
# Commands: gameplay names (DynamicStringMapping, int-Id + IdStr tables)
# ---------------------------------------------------------------------------
#
# rawStoryNameTypeMapping (above) is the only DynamicStringMapping table with
# `Ids: [{Value: str}, ...]`. Several other tables in the same asset --
# cardNameTypeMapping, encounterIdTypeMapping (Reflect/Connect encounter
# titles), songIdTitleTypeMapping, recipeIdTypeMapping, etc. -- share a
# different, simpler shape: `Ids: [int, ...]` with a parallel `IdStr: [str,
# ...]` giving each entry a human-readable key (e.g. "1-1-a", "2-r-7"). These
# were previously left untouched as "gameplay strings"; extract/pack for two
# of them (cards, encounters) are wired up below on request. Add another
# table by reusing these two helpers with a new `table_key`/label.


def _dyn_table_id_value(raw):
    """Ids in these tables are either a bare int (cardNameTypeMapping) or a
    {Value: int} dict (encounterIdTypeMapping, like rawStoryNameTypeMapping's
    {Value: str}) -- normalize to a plain int either way."""
    return raw["Value"] if isinstance(raw, dict) else raw


def _dyn_table_to_entries(tt, table_key):
    m = tt[table_key]
    ids, idstrs, vals = m["Ids"], m["IdStr"], m["IdValues"]
    if not (len(ids) == len(idstrs) == len(vals)):
        raise SystemExit(f"error: Ids/IdStr/IdValues length mismatch in {table_key}")
    return [
        {
            "Id": _dyn_table_id_value(i),
            "IdStr": s,
            "English": v.get("English", ""),
            "Japanese": v.get("Japanese", ""),
            "Korean": v.get("Korean", ""),
            "TraditionalChinese": v.get("TraditionalChinese", ""),
            "SimplifiedChinese": v.get("SimplifiedChinese", ""),
        }
        for i, s, v in zip(ids, idstrs, vals)
    ]


def _cmd_extract_dyn_table(game, table_key, out_name, label):
    index = game.load_index()
    fn, _env, _obj, tt = load_asset_by_address(game, ADDR_DYNAMIC_STRING_MAPPING, index)
    entries = _dyn_table_to_entries(tt, table_key)
    out_dir = os.path.join(game.workspace, "work", "names")
    write_json(os.path.join(out_dir, out_name), {"entries": entries})
    log(f"extracted {len(entries)} {label} entries -> {out_dir}/{out_name}")
    log(f"bundle: {fn}")


def _cmd_pack_dyn_table(args, game, table_key, out_name, label):
    json_path = os.path.join(game.workspace, "work", "names", out_name)
    if not os.path.exists(json_path):
        raise SystemExit(f"error: run the matching extract command first ({json_path} missing)")
    data = read_json(json_path)
    index = game.load_index()
    fn, env, obj, tt = load_asset_by_address(game, ADDR_DYNAMIC_STRING_MAPPING, index, prefer_patch=True)
    m = tt[table_key]
    ids, idstrs, vals = m["Ids"], m["IdStr"], m["IdValues"]
    entries = data["entries"]
    if len(entries) != len(ids):
        raise SystemExit(
            f"error: entry count mismatch (json={len(entries)} asset={len(ids)}); "
            "do not add/remove entries, edit fields only."
        )
    for i, e in enumerate(entries):
        if e["Id"] != _dyn_table_id_value(ids[i]) or e["IdStr"] != idstrs[i]:
            raise SystemExit(
                f"error: entry {i} id mismatch ({e['Id']!r}/{e['IdStr']!r} != "
                f"{_dyn_table_id_value(ids[i])!r}/{idstrs[i]!r}); order must match the extracted file."
            )
    src_field, dst_field = args.locale_map.split("->")
    field_to_key = {
        "English": "English",
        "Japanese": "Japanese",
        "Korean": "Korean",
        "ChineseTC": "TraditionalChinese",
        "ChineseSC": "SimplifiedChinese",
    }
    if src_field not in field_to_key or dst_field not in field_to_key:
        raise SystemExit(f"error: --locale-map fields must be among {TEXT_FIELDS}")
    changed = 0
    for i, e in enumerate(entries):
        src = (e.get(src_field) or "").strip()
        if src:
            vals[i][field_to_key[dst_field]] = src
            changed += 1
    log(f"applied {changed}/{len(entries)} {label} entries ({src_field} -> {dst_field})")
    if changed == 0:
        log("nothing to pack (no non-empty source fields); skipping")
        return
    if args.dry_run:
        log("[dry-run] bundle would be written (skipped)")
        return
    obj.save_typetree(tt)
    commit_or_dry(args, game, fn, "DynamicStringMapping", env)


def cmd_extract_card_names(args, game):
    _cmd_extract_dyn_table(game, "cardNameTypeMapping", "card_names.json", "card-name")


def cmd_pack_card_names(args, game):
    _cmd_pack_dyn_table(args, game, "cardNameTypeMapping", "card_names.json", "card-name")


def cmd_extract_encounter_names(args, game):
    _cmd_extract_dyn_table(game, "encounterIdTypeMapping", "encounter_names.json", "encounter-name")


def cmd_pack_encounter_names(args, game):
    _cmd_pack_dyn_table(args, game, "encounterIdTypeMapping", "encounter_names.json", "encounter-name")


def cmd_extract_recipe_names(args, game):
    _cmd_extract_dyn_table(game, "recipeIdTypeMapping", "recipe_names.json", "recipe-name")


def cmd_pack_recipe_names(args, game):
    _cmd_pack_dyn_table(args, game, "recipeIdTypeMapping", "recipe_names.json", "recipe-name")


# ---------------------------------------------------------------------------
# Commands: UI strings (Str.StringsMapping, in infalsus_Data/resources.assets)
# ---------------------------------------------------------------------------
#
# This asset is outside the Addressables bundle system that every other
# command here works on, and unlike those bundles it ships with no embedded
# Unity typetree (normal for IL2CPP main-data files) -- UnityPy can't read
# its MonoBehaviours out of the box. To get a typetree we hand UnityPy a set
# of "DummyDLL" stub assemblies (field-accurate, IL-stripped .NET DLLs)
# generated from the game's own GameAssembly.dll + global-metadata.dat via
# Cpp2IL. See README.md "UI strings (StringsMapping)" for how to (re)generate
# work/il2cpp_dlls/ if it's missing.


def il2cpp_dll_dir(game):
    return os.path.join(game.workspace, "work", "il2cpp_dlls")


def load_il2cpp_generator(game):
    from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

    dll_dir = il2cpp_dll_dir(game)
    if not os.path.isdir(dll_dir) or not any(f.endswith(".dll") for f in os.listdir(dll_dir)):
        raise SystemExit(
            f"error: {dll_dir} has no DummyDLLs.\n"
            "Generate them once with Cpp2IL against your own game install:\n"
            '  Cpp2IL --game-path "<In Falsus install dir>" --output-as dummydll '
            f"--output-to {dll_dir}\n"
            "See README.md \"UI strings (StringsMapping)\" for details."
        )
    gen = TypeTreeGenerator(UNITY_ENGINE_VERSION, generator="AssetsTools")
    n = 0
    for fn in sorted(os.listdir(dll_dir)):
        if not fn.endswith(".dll"):
            continue
        with open(os.path.join(dll_dir, fn), "rb") as f:
            data = f.read()
        try:
            gen.load_dll(data)
            n += 1
        except Exception as e:
            log(f"  warning: failed to load {fn}: {e}")
    if n == 0:
        raise SystemExit(f"error: found .dll files in {dll_dir} but none loaded successfully")
    return gen


def load_ui_strings_env(game):
    """Load resources.assets (+ its sibling globalgamemanagers.assets, needed
    to resolve the MonoScript PPtr) with the IL2CPP typetree generator
    attached, and return (env, obj) for the StringsMapping MonoBehaviour."""
    gen = load_il2cpp_generator(game)
    path = os.path.join(game.data_dir, UI_STRINGS_DATA_FILE)
    if not os.path.exists(path):
        raise SystemExit(f"error: {path} not found")
    env = UnityPy.load(path)
    env.typetree_generator = gen
    obj = None
    for o in env.objects:
        if o.type.name == "MonoBehaviour" and o.path_id == UI_STRINGS_PATH_ID:
            obj = o
            break
    if obj is None:
        raise SystemExit(
            f"error: no MonoBehaviour with path_id {UI_STRINGS_PATH_ID} in {UI_STRINGS_DATA_FILE} "
            "(wrong game build? re-check the address)"
        )
    return env, obj


def strings_key_names(game):
    """{int Key -> C# enum member name}, parsed from the decompiled
    Str.Strings.cs cached in work/il2cpp_dlls/ (see README). Purely a label
    for the translator's convenience -- `pack-ui-strings` matches by the raw
    integer Key, never by name."""
    src = os.path.join(il2cpp_dll_dir(game), "Str.Strings.cs")
    if not os.path.exists(src):
        return {}
    with open(src, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"public enum Key\s*\{(.*?)\n\t\}", text, re.S)
    if not m:
        return {}
    pairs = re.findall(r"^\s*(\w+)\s*=\s*(\d+),?\s*$", m.group(1), re.M)
    return {int(v): k for k, v in pairs}


def cmd_extract_ui_strings(args, game):
    env, obj = load_ui_strings_env(game)
    tt = obj.read_typetree()
    if tt.get("m_Name") != UI_STRINGS_SCRIPT_NAME:
        raise SystemExit(f"error: object at path_id {UI_STRINGS_PATH_ID} is {tt.get('m_Name')!r}, expected {UI_STRINGS_SCRIPT_NAME!r}")
    key_names = strings_key_names(game)
    mappings = tt["Mappings"]
    out_dir = os.path.join(game.workspace, "work", "ui_strings")
    os.makedirs(out_dir, exist_ok=True)
    entries = []
    for m in mappings:
        entries.append(
            {
                "Key": m["Key"],
                "KeyName": key_names.get(m["Key"], f"Key_{m['Key']}"),
                **{f: m[f] for f in UI_STRINGS_FIELDS},
            }
        )
    write_json(os.path.join(out_dir, "ui_strings.json"), {"entries": entries})
    tsv_path = os.path.join(out_dir, "ui_strings.tsv")
    with open(tsv_path, "w", encoding="utf-8", newline="") as f:
        f.write("Key\tKeyName\tEnglish\tJapanese\tKorean\n")
        for e in entries:
            f.write(
                str(e["Key"]) + "\t" + e["KeyName"] + "\t"
                + e["English"].replace("\t", " ").replace("\n", "\\n") + "\t"
                + e["Japanese"].replace("\t", " ").replace("\n", "\\n") + "\t"
                + e["Korean"].replace("\t", " ").replace("\n", "\\n") + "\n"
            )
    log(f"extracted {len(entries)} UI string entries -> {out_dir}")
    log(f"data file: {UI_STRINGS_DATA_FILE} (path_id {UI_STRINGS_PATH_ID})")


def cmd_pack_ui_strings(args, game):
    ui_path = os.path.join(game.workspace, "work", "ui_strings", "ui_strings.json")
    if not os.path.exists(ui_path):
        raise SystemExit("error: run `extract-ui-strings` first")
    data = read_json(ui_path)
    edits_by_key = {e["Key"]: e for e in data["entries"]}
    src_field, dst_field = args.locale_map.split("->")
    if src_field not in UI_STRINGS_FIELDS or dst_field not in UI_STRINGS_FIELDS:
        raise SystemExit(f"error: --locale-map fields must be among {UI_STRINGS_FIELDS}")

    env, obj = load_ui_strings_env(game)
    tt = obj.read_typetree()
    mappings = tt["Mappings"]
    missing = [m["Key"] for m in mappings if m["Key"] not in edits_by_key]
    if missing and not args.allow_partial:
        raise SystemExit(
            f"error: {len(missing)} keys missing from edited file (e.g. {missing[:5]}); "
            "re-run `extract-ui-strings`, or pass --allow-partial."
        )
    changed = 0
    for m in mappings:
        e = edits_by_key.get(m["Key"])
        if not e:
            continue
        src = (e.get(src_field) or "").strip()
        if src:
            m[dst_field] = src
            changed += 1
    log(f"applied {changed}/{len(mappings)} UI string entries ({src_field} -> {dst_field})")
    if changed == 0:
        log("nothing to pack (no non-empty source fields); skipping")
        return
    if args.dry_run:
        log("[dry-run] data file would be written (skipped)")
        return
    obj.save_typetree(tt)
    out_rel = os.path.join(GAME_DATA_DIRNAME, UI_STRINGS_DATA_FILE)
    out_path = os.path.join(game.patch_dir, out_rel)
    game_path = os.path.join(game.data_dir, UI_STRINGS_DATA_FILE)
    if os.path.exists(game_path):
        backup_file(game, game_path, os.path.join("data", UI_STRINGS_DATA_FILE))
    data_bytes = env.file.save()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    atomic_write_bytes(out_path, data_bytes)
    log(f"packed StringsMapping -> {out_path}")


# ---------------------------------------------------------------------------
# Commands: fonts
# ---------------------------------------------------------------------------


def cmd_extract_fonts(args, game):
    index = game.load_index()
    fn = game.find_font_bundle(index)
    log(f"font bundle: {fn}")
    env = UnityPy.load(os.path.join(game.bundles_dir, fn))
    families = {}
    assets = {}
    os.makedirs(os.path.join(game.workspace, "work", "fonts"), exist_ok=True)
    monos = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tt = obj.read_typetree()
        except Exception:
            continue
        monos.append((obj, tt))
    # pass 1: font assets (need their identifiers before resolving families)
    for _obj, tt in monos:
        if "Identifier" in tt:
            raw = bytes(tt.get("RawBytes") or [])
            ident = tt["Identifier"]
            ext = sniff_font_ext(raw)
            assets[_obj.path_id] = {
                "Identifier": ident,
                "PointSizeMultiplier": tt.get("PointSizeMultiplier", 1.0),
                "size": len(raw),
                "ext": ext,
            }
            with open(os.path.join(game.workspace, "work", "fonts", ident + ext), "wb") as f:
                f.write(raw)
    # pass 2: families
    for _obj, tt in monos:
        if "fontAssets" not in tt:
            continue

        def refname(r):
            return assets.get(r["m_PathID"], {}).get("Identifier", f"pid:{r['m_PathID']}")

        families[tt.get("m_Name", "?")] = {
            "supportsLocalization": tt.get("supportsLocalization", 0),
            "fontAssets": [refname(r) for r in tt["fontAssets"]],
            "nonEnglishLocalizationToFontSet": [
                [refname(r) for r in s["FontAssets"]]
                for s in tt.get("nonEnglishLocalizationToFontSet", [])
            ],
        }
    out = os.path.join(game.workspace, "work", "fonts", "fonts.json")
    write_json(out, {"bundle": fn, "families": families, "assets": list(assets.values())})
    log(f"extracted {len(assets)} fonts, {len(families)} families -> {os.path.dirname(out)}")


def cmd_list_fonts(args, game):
    fonts_json = os.path.join(game.workspace, "work", "fonts", "fonts.json")
    if not os.path.exists(fonts_json):
        raise SystemExit("error: run `extract-fonts` first")
    data = read_json(fonts_json)
    for fam, info in data["families"].items():
        print(f"===== {fam}  (supportsLocalization={info['supportsLocalization']})")
        print("  EN base:", info["fontAssets"])
        for i, s in enumerate(info["nonEnglishLocalizationToFontSet"]):
            print(f"  set[{i}]:", s)
    print("===== FastTextAssets")
    for a in data["assets"]:
        print(f"  {a['Identifier']:<32} {a['ext']}  {a['size']:>9} bytes")


def cmd_pack_fonts(args, game):
    fonts_json = os.path.join(game.workspace, "work", "fonts", "fonts.json")
    if not os.path.exists(fonts_json):
        raise SystemExit("error: run `extract-fonts` first")
    data = read_json(fonts_json)
    index = game.load_index()
    fn = game.find_font_bundle(index)
    env = UnityPy.load(os.path.join(game.bundles_dir, fn))
    pid_to_obj = {}
    ident_to_pid = {}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tt = obj.read_typetree()
        except Exception:
            continue
        if "Identifier" in tt:
            ident_to_pid[tt["Identifier"]] = obj.path_id
            pid_to_obj[obj.path_id] = (obj, tt)
    # resolve replacement set: identifier -> ttf path
    replacements = {}
    if args.preset == "notokr":
        for ident, src in [
            ("Supreme-Regular", "NotoSerifKR-Regular"),
            ("Supreme-Bold", "NotoSerifKR-Bold"),
            ("Supreme-Medium", "NotoSerifKR-Bold"),
            ("BaiJamjuree-Regular", "NotoSerifKR-Regular"),
            ("BaiJamjuree-Bold", "NotoSerifKR-Bold"),
            ("BaiJamjuree-Light", "NotoSerifKR-Regular"),
            ("BaiJamjuree-Medium", "NotoSerifKR-Regular"),
            ("BaiJamjuree-SemiBold", "NotoSerifKR-Bold"),
        ]:
            replacements[ident] = os.path.join(
                game.workspace, "work", "fonts", src
            ) + (".otf" if os.path.exists(os.path.join(game.workspace, "work", "fonts", src + ".otf")) else ".ttf")
    elif args.preset == "nanum":
        nanum_dir = os.path.join(game.workspace, "tools", "fonts")
        for ident, src in [
            ("Supreme-Regular", "NanumBarunGothic.ttf"),
            ("Supreme-Bold", "NanumBarunGothicBold.ttf"),
            ("Supreme-Medium", "NanumBarunGothicBold.ttf"),
            ("BaiJamjuree-Regular", "NanumBarunGothic.ttf"),
            ("BaiJamjuree-Bold", "NanumBarunGothicBold.ttf"),
            ("BaiJamjuree-Light", "NanumBarunGothic.ttf"),
            ("BaiJamjuree-Medium", "NanumBarunGothic.ttf"),
            ("BaiJamjuree-SemiBold", "NanumBarunGothicBold.ttf"),
        ]:
            replacements[ident] = os.path.join(nanum_dir, src)
    elif args.preset == "none":
        pass
    for pair in args.set or []:
        if "=" not in pair:
            raise SystemExit(f"error: --set expects Identifier=path.ttf, got {pair!r}")
        ident, ttf = pair.split("=", 1)
        replacements[ident] = ttf
    if not replacements:
        raise SystemExit("error: nothing to replace; use --set or --preset")
    for ident, ttf_path in replacements.items():
        if ident not in ident_to_pid:
            raise SystemExit(f"error: unknown FastTextAsset identifier {ident!r}")
        if not os.path.exists(ttf_path):
            raise SystemExit(f"error: font file not found: {ttf_path}")
        fdata = open(ttf_path, "rb").read()
        if not is_valid_font(fdata):
            raise SystemExit(f"error: {ttf_path} does not look like a TTF/OTF font")
        obj, tt = pid_to_obj[ident_to_pid[ident]]
        tt["RawBytes"] = list(fdata)
        obj.save_typetree(tt)
        log(f"  replaced {ident} <- {ttf_path} ({len(fdata)} bytes)")
    commit_or_dry(args, game, fn, "fonts", env)


# ---------------------------------------------------------------------------
# Commands: verify / restore
# ---------------------------------------------------------------------------


def cmd_verify(args, game):
    if not run_verify(game):
        sys.exit(1)


def run_verify(game):
    """Consistency checks against the current work/ files. Returns True/False
    instead of exiting, so `repack` can gate packing on the result. Also
    reachable directly as the `verify` subcommand."""
    ok = True
    scripts_dir = os.path.join(game.workspace, "work", "scripts")
    trans_dir = os.path.join(game.workspace, "work", "translations")
    # 1. scripts: every s has an id; ids exist in the table
    if os.path.isdir(scripts_dir):
        script_ids = set()
        orphan_s = 0
        for root, _dirs, files in os.walk(scripts_dir):
            for f in files:
                if not f.endswith((".sps", ".spi", ".spp")):
                    continue
                text = open(os.path.join(root, f), encoding="utf-8").read()
                cur_id = None
                for ln in text.splitlines():
                    ls = ln.strip()
                    m = re.match(r"^id\s+([0-9A-Za-z_.-]+)\s*$", ls)
                    if m:
                        cur_id = m.group(1)
                        script_ids.add(cur_id)
                        continue
                    if ls == "s" or re.match(r"^s\s", ls):
                        if cur_id is None:
                            orphan_s += 1
        print(f"script ids: {len(script_ids)}, s-commands without id: {orphan_s}")
        if orphan_s:
            ok = False
    if os.path.isdir(trans_dir):
        table = read_json(os.path.join(trans_dir, "story_translations.json"))["Translations"]
        table_ids = {e["Id"] for e in table}
        if os.path.isdir(scripts_dir):
            missing = script_ids - table_ids
            print(f"script ids missing from table: {len(missing)}")
            if missing:
                ok = False
        # 2. by_story files cover the table
        by_story_dir = os.path.join(trans_dir, "by_story")
        if os.path.isdir(by_story_dir):
            edit_ids = set()
            dup = []
            for f in sorted(os.listdir(by_story_dir)):
                if not f.endswith(".json"):
                    continue
                for e in read_json(os.path.join(by_story_dir, f))["entries"]:
                    if e["Id"] in edit_ids:
                        dup.append(e["Id"])
                    edit_ids.add(e["Id"])
            print(f"editable entries: {len(edit_ids)}, table entries: {len(table_ids)}")
            miss = table_ids - edit_ids
            extra = edit_ids - table_ids
            if dup:
                print(f"DUPLICATE ids in editable files: {dup[:10]}")
                ok = False
            if miss:
                print(f"ids missing from editable files: {len(miss)} (e.g. {sorted(miss)[:5]})")
                ok = False
            if extra:
                print(f"unknown ids in editable files: {len(extra)} (e.g. {sorted(extra)[:5]})")
                ok = False
        # 3. names
        names_path = os.path.join(game.workspace, "work", "names", "names.json")
        if os.path.exists(names_path):
            entries = read_json(names_path)["entries"]
            print(f"name entries: {len(entries)}")
    # 4. fonts
    fonts_json = os.path.join(game.workspace, "work", "fonts", "fonts.json")
    if os.path.exists(fonts_json):
        data = read_json(fonts_json)
        bad = []
        for a in data["assets"]:
            p = os.path.join(game.workspace, "work", "fonts", a["Identifier"] + a["ext"])
            if not os.path.exists(p) or not is_valid_font(open(p, "rb").read()):
                bad.append(a["Identifier"])
        print(f"fonts: {len(data['assets'])}, invalid: {bad}")
        if bad:
            ok = False
    print("VERIFY:", "OK" if ok else "PROBLEMS FOUND")
    return ok


def cmd_restore(args, game):
    backups = os.path.join(game.workspace, "backups")
    n = 0
    for root, _dirs, files in os.walk(backups):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), backups)
            if rel.startswith("bundles" + os.sep):
                dst = os.path.join(game.bundles_dir, os.path.basename(f))
            elif rel.startswith("sam" + os.sep):
                dst = os.path.join(game.sam_dir, f)
            else:
                continue
            shutil.copy2(os.path.join(root, f), dst)
            n += 1
            log(f"restored {dst}")
    log(f"restored {n} files from {backups}")


# ---------------------------------------------------------------------------
# Commands: unpack / repack (one-command entry points)
# ---------------------------------------------------------------------------
#
# Everything above this point is one narrow step in a longer pipeline
# (extract this table, pack that table, sync this file format into that
# one). For day-to-day translating, nobody wants to remember that order.
# `unpack` runs every extract-* step plus a translation/ -> work/ sync in
# one call; `repack` runs a sync + sanity check + every pack-* step (for
# the text tables -- fonts are a separate one-time setup, see `pack-fonts`)
# in one call, and refuses to write a patch if the sanity check fails.


def _ko_io():
    # tools/ is already on sys.path when this script is run directly
    # (python puts the script's own directory at sys.path[0]).
    import ko_io
    return ko_io


def cmd_unpack(args, game):
    log("=== unpack 1/2: extracting game text ===")
    cmd_extract_scripts(args, game)
    cmd_extract_translations(args, game)
    cmd_extract_context(args, game)
    cmd_extract_names(args, game)
    cmd_extract_card_names(args, game)
    cmd_extract_encounter_names(args, game)
    cmd_extract_recipe_names(args, game)
    dll_dir = il2cpp_dll_dir(game)
    if os.path.isdir(dll_dir) and any(f.endswith(".dll") for f in os.listdir(dll_dir)):
        cmd_extract_ui_strings(args, game)
    else:
        log(f"skipping extract-ui-strings: {dll_dir} not set up (see README §4.5 for the one-time setup)")

    log("=== unpack 2/2: merging translation/ into work/ ===")
    counts = _ko_io().sync()
    log(
        f"  {counts['stories']} dialogue lines, {counts['names']} names, "
        f"{counts['ui_strings']} UI strings, {counts['card_names']} card names, "
        f"{counts['encounter_names']} encounter names, {counts['recipe_names']} recipe names already translated"
    )
    log("unpack complete. Translate translation/ko/*.txt, translation/*.tsv, then run `repack`.")


def cmd_repack(args, game):
    ko_io = _ko_io()
    log("=== repack 1/3: syncing translation/ into work/ ===")
    counts = ko_io.sync()
    log(
        f"  {counts['stories']} dialogue lines, {counts['names']} names, "
        f"{counts['ui_strings']} UI strings, {counts['card_names']} card names, "
        f"{counts['encounter_names']} encounter names, {counts['recipe_names']} recipe names"
    )

    log("=== repack 2/3: sanity check ===")
    if not run_verify(game) and not args.skip_verify:
        raise SystemExit(
            "error: sanity check failed (see above) -- fix the issues, or re-run "
            "with --skip-verify to pack anyway"
        )

    log("=== repack 3/3: packing ===")
    cmd_pack_translations(args, game)
    cmd_pack_names(args, game)
    cmd_pack_card_names(args, game)
    cmd_pack_encounter_names(args, game)
    cmd_pack_recipe_names(args, game)
    dll_dir = il2cpp_dll_dir(game)
    if os.path.isdir(dll_dir) and any(f.endswith(".dll") for f in os.listdir(dll_dir)):
        cmd_pack_ui_strings(args, game)
    else:
        log(f"skipping pack-ui-strings: {dll_dir} not set up (see README §4.5 for the one-time setup)")

    if args.dry_run:
        log("=== repack complete (dry run -- nothing written) ===")
    else:
        log(f"=== repack complete. Patch output: {game.patch_dir} ===")
        log("Fonts are a separate one-time step -- see `pack-fonts` (README §4.6) if not done yet.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ws_default = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--game-path", help="path to the In Falsus install dir (contains infalsus_Data)")
    p.add_argument("--workspace", default=ws_default, help="tool workspace dir (default: repo root)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("unpack", help="one-command extract: every extract-* step + sync translation/ into work/").set_defaults(func=cmd_unpack)
    sp = sub.add_parser("repack", help="one-command pack: sync + sanity check + every pack-* step (text tables; fonts are separate)")
    sp.add_argument("--locale-map", default="Korean->English",
                    help="source->target field, applied to every table, e.g. Korean->English (default)")
    sp.add_argument("--allow-partial", action="store_true", help="pack even if some ids/keys are missing from work/")
    sp.add_argument("--skip-verify", action="store_true", help="pack even if the sanity check finds problems")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_repack)

    sub.add_parser("locate", help="show detected game paths").set_defaults(func=cmd_locate)
    sp = sub.add_parser("index", help="(re)build the bundle index cache")
    sp.add_argument("--refresh", action="store_true")
    sp.set_defaults(func=cmd_index)

    sub.add_parser("extract-scripts", help="decrypt SAM script files to text").set_defaults(func=cmd_extract_scripts)
    sub.add_parser("pack-scripts", help="re-encrypt edited script text into the game").set_defaults(func=cmd_pack_scripts)
    sub.add_parser("extract-context", help="merge speaker info into per-story translation files").set_defaults(func=cmd_extract_context)

    sub.add_parser("extract-translations", help="dump StoryTranslationDetails to JSON/TSV").set_defaults(func=cmd_extract_translations)
    sp = sub.add_parser("pack-translations", help="pack edited translations back into the game")
    sp.add_argument("--locale-map", default="Korean->English",
                    help="source->target field, e.g. Korean->English (default) or Korean->Korean")
    sp.add_argument("--allow-partial", action="store_true")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_pack_translations)

    sub.add_parser("extract-names", help="dump character name table to JSON").set_defaults(func=cmd_extract_names)
    sp = sub.add_parser("pack-names", help="pack edited names back into the game")
    sp.add_argument("--locale-map", default="Korean->English")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_pack_names)

    sub.add_parser("extract-card-names", help="dump card-name table to JSON").set_defaults(func=cmd_extract_card_names)
    sp = sub.add_parser("pack-card-names", help="pack edited card names back into the game")
    sp.add_argument("--locale-map", default="Korean->English")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_pack_card_names)

    sub.add_parser("extract-encounter-names", help="dump encounter/Reflect-title table to JSON").set_defaults(func=cmd_extract_encounter_names)
    sp = sub.add_parser("pack-encounter-names", help="pack edited encounter names back into the game")
    sp.add_argument("--locale-map", default="Korean->English")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_pack_encounter_names)

    sub.add_parser("extract-recipe-names", help="dump recipe/card-name table to JSON").set_defaults(func=cmd_extract_recipe_names)
    sp = sub.add_parser("pack-recipe-names", help="pack edited recipe names back into the game")
    sp.add_argument("--locale-map", default="Korean->English")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_pack_recipe_names)

    sub.add_parser("extract-ui-strings", help="dump Str.StringsMapping (UI chrome text) to JSON/TSV").set_defaults(func=cmd_extract_ui_strings)
    sp = sub.add_parser("pack-ui-strings", help="pack edited UI strings back into resources.assets")
    sp.add_argument("--locale-map", default="Korean->English",
                    help="source->target field, e.g. Korean->English (default, EN-locale carry)")
    sp.add_argument("--allow-partial", action="store_true")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_pack_ui_strings)

    sub.add_parser("extract-fonts", help="extract embedded fonts and font families").set_defaults(func=cmd_extract_fonts)
    sub.add_parser("list-fonts", help="show font families and their per-locale sets").set_defaults(func=cmd_list_fonts)
    sp = sub.add_parser("pack-fonts", help="replace embedded font binaries")
    sp.add_argument("--set", action="append", metavar="Identifier=path.ttf")
    sp.add_argument("--preset", choices=["none", "notokr", "nanum"], default="none")
    sp.add_argument("--dry-run", action="store_true", help="validate only; do not write")
    sp.set_defaults(func=cmd_pack_fonts)

    sub.add_parser("verify", help="consistency checks").set_defaults(func=cmd_verify)
    sub.add_parser("restore", help="restore all original files from backups").set_defaults(func=cmd_restore)

    args = p.parse_args()
    game = Game.autodetect(args.workspace, args.game_path)
    args.func(args, game)


if __name__ == "__main__":
    main()
