#!/bin/zsh
# Copy the Music folder of the music library to a backup drive, plus a timestamped known-good file list.
#   ./backup_music.sh /Volumes/Backup            check, copy, write manifest
#   ./backup_music.sh /Volumes/Backup --force    copy even if the library check finds problems
# Result on the drive:
#   <dest>/Music/                                     accumulating copy (rsync -a, never deletes)
#   <dest>/Music manifests/Music-YYYY-MM-DD-HHMM.tsv  the files that made up the library at that time
set -e
DEST=${1:?usage: backup_music.sh /Volumes/Backup [--force]}
REPO=${0:A:h}
[[ -d $DEST ]] || { echo "No such folder: $DEST"; exit 1; }
SRC=$(cd "$REPO" && python3 -c 'import mlt_config as C, os; print(os.path.join(C.LIBRARY, "Music"))')
STAMP=$(date +%Y-%m-%d-%H%M)

echo "== Checking the library"
RESULT=$(cd "$REPO" && ./sync_check.py library-check 2>&1 | tail -1)
echo "$RESULT"
if [[ $RESULT != *"all in sync"* && $2 != --force ]]; then
  echo "Library is not in sync; not backing up. Fix it, or rerun with --force."; exit 1
fi

echo "== Copying $SRC/ -> $DEST/Music/"
/usr/bin/rsync -a --partial --exclude "*.movpkg" "$SRC/" "$DEST/Music/"

echo "== Writing the known-good list"
mkdir -p "$DEST/Music manifests"
(cd "$REPO" && ./sync_check.py manifest "$DEST/Music manifests/Music-$STAMP.tsv")
echo "Done: $DEST/Music and $DEST/Music manifests/Music-$STAMP.tsv"
