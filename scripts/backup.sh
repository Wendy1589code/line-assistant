#!/usr/bin/env bash
#
# Back up the BirdAssistant runtime state (user data + secrets + .env).
# Runs ON the VM, typically from cron. Version-controlled so it survives a rebuild.
#
# Usage (on the VM):
#   /opt/line-assistant/scripts/backup.sh
#
# Env overrides:
#   APP_DIR     project dir            (default /opt/line-assistant)
#   BACKUP_DIR  where tarballs land    (default /opt/backups)
#   KEEP_DAYS   retention in days      (default 14)
#   OFFSITE     optional rsync target  (e.g. user@host:/path or s3 via your own wrapper)
#
# NOTE: backups contain OAuth tokens and secrets — treat the tarballs as sensitive.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/line-assistant}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
OFFSITE="${OFFSITE:-}"

stamp="$(date +%Y%m%d-%H%M%S)"
archive="${BACKUP_DIR}/data-${stamp}.tar.gz"
log="${BACKUP_DIR}/backup.log"

mkdir -p "$BACKUP_DIR"

note() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$log"; }

cd "$APP_DIR"

# Build the list of things to back up, skipping any that don't exist.
targets=()
for t in data secrets .env; do
  [ -e "$t" ] && targets+=("$t")
done
if [ "${#targets[@]}" -eq 0 ]; then
  note "ERROR: nothing to back up in $APP_DIR (no data/ secrets/ .env)"
  exit 1
fi

note "backup start -> $archive (targets: ${targets[*]})"
tar czf "$archive" "${targets[@]}"

# Verify the archive is readable before we trust it / rotate old ones.
if ! tar tzf "$archive" >/dev/null 2>&1; then
  note "ERROR: archive failed integrity check, removing $archive"
  rm -f "$archive"
  exit 1
fi
size="$(du -h "$archive" | cut -f1)"
note "backup ok ($size)"

# Optional off-site copy (best-effort; failure is logged but doesn't fail the job).
if [ -n "$OFFSITE" ]; then
  if rsync -az -e 'ssh -o BatchMode=yes -o ConnectTimeout=15' "$archive" "$OFFSITE" 2>>"$log"; then
    note "offsite copy ok -> $OFFSITE"
  else
    note "WARNING: offsite copy to $OFFSITE failed"
  fi
fi

# Rotate: delete archives older than KEEP_DAYS.
deleted="$(find "$BACKUP_DIR" -name 'data-*.tar.gz' -mtime "+${KEEP_DAYS}" -print -delete | wc -l | tr -d ' ')"
note "rotation done (removed ${deleted} archive(s) older than ${KEEP_DAYS}d)"
