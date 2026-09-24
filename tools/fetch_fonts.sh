#!/bin/sh
# Fetch pristine (unpatched) Korean fonts.
#
# NanumBarunGothic (Naver) is a Gothic/sans face, matching the design of the
# English-base fonts it replaces (Supreme-*, BaiJamjuree-*). Its licence
# permits free use, modification and redistribution; the licence text is
# downloaded alongside the fonts and MUST accompany any redistribution.
#
# The distributed, line-metric-patched copies live in fonts/ (see README
# section 4.6) -- use those for `pack-fonts`. This script only re-fetches the
# pristine originals into work/fonts/ (gitignored), e.g. to redo the patch.
set -e
DIR="$(dirname "$0")/../work/fonts"
BASE="https://raw.githubusercontent.com/hiun/NanumBarunGothic/master"
mkdir -p "$DIR"
for f in NanumBarunGothic NanumBarunGothicBold NanumBarunGothicLight; do
    echo "fetching $f.ttf"
    curl -fsSL -o "$DIR/$f.ttf" "$BASE/$f.ttf"
done
curl -fsSL -o "$DIR/NanumBarunGothic-LICENSE.txt" "$BASE/LICENSE"
echo "fonts in $DIR"
