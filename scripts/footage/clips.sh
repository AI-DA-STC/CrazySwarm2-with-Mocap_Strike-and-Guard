#!/bin/bash
# Fly, film and cut every clip in clips.tsv, or only the names given. Needs `rig.sh up`.
# About 4 minutes a clip. PUBLISH=1 copies the WebPs into docs/img/guard/ afterwards.
#
#   scripts/footage/clips.sh                 # all of them
#   scripts/footage/clips.sh zone flood      # just these
#   FILM_ONLY=1 scripts/footage/clips.sh     # re-film + re-cut existing bags (no flying)
#   CUT_ONLY=1 PUBLISH=1 scripts/footage/clips.sh   # re-cut existing takes, copy to the docs
D=$(dirname "$0")
source "$D/common.sh"
# fd 3, and </dev/null below: ros2/curl/ffmpeg inside the loop would otherwise eat the list
while IFS=$'\t' read -r name values head line <&3; do
  [[ -z "$name" || "$name" == \#* ]] && continue
  [ $# -gt 0 ] && [[ " $* " != *" $name "* ]] && continue
  echo "=== $name"
  if [ -n "$CUT_ONLY" ]; then :
  elif [ -n "$FILM_ONLY" ]; then "$D/film.sh" "$name" < /dev/null
  else "$D/take.sh" "$name" "$values" < /dev/null | tail -2; fi
  "$D/cut.sh" "$name" "$name" "$head" "$line" < /dev/null
  [ -n "$PUBLISH" ] && mkdir -p "$REPO/docs/img/guard" && cp "$WORK/clips/$name.webp" "$REPO/docs/img/guard/"
done 3< "$D/clips.tsv"
echo "clips in $WORK/clips${PUBLISH:+ (and docs/img/guard/)}"
