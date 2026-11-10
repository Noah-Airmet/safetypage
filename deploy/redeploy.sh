#!/bin/sh
# Put a sealed snapshot live: copy it to the server, switch the stack to it, then build and
# publish the site against it.
#
#   deploy/redeploy.sh data/snapshots/2026.11.1
#
# Settings come from the environment or from deploy/.env (untracked):
#   DEPLOY_HOST      ssh name of the machine that runs deploy/server/compose.yaml   (required)
#   DEPLOY_REPO      this repository's checkout there          (default /opt/safetypage)
#   DEPLOY_DATA      where snapshots are kept there            (default /srv/safetypage)
#   DEPLOY_BWLIMIT   rsync's transfer cap, KB/s                (default 40000)
#   CLOUDFLARE_ACCOUNT_ID and a Cloudflare credential wrangler accepts, for the Pages upload
#
# The server's code is whatever is pushed to the checkout's branch. Old snapshots stay on the
# server until someone removes them.
set -eu
cd "$(dirname "$0")/.."
if [ -f deploy/.env ]; then set -a; . deploy/.env; set +a; fi
set -a; . site/deploy.env; set +a

snap=${1:?usage: deploy/redeploy.sh <snapshot dir>}
snap=$(cd "$snap" && pwd)
host=${DEPLOY_HOST:?set DEPLOY_HOST (see the top of this file)}
repo=${DEPLOY_REPO:-/opt/safetypage}
data=${DEPLOY_DATA:-/srv/safetypage}
id=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["snapshot_id"])' "$snap/manifest.json")
echo "snapshot $id -> $host:$data/snapshots/$id"

# 1. Copy. Files that are byte-identical in the snapshot now live are linked, not sent again.
live=$(ssh "$host" "sed -n 's/^SNAPSHOT_ID=//p' $repo/deploy/server/.env 2>/dev/null" || true)
link=
if [ -n "$live" ] && [ "$live" != "$id" ]; then link="--link-dest=$data/snapshots/$live/"; fi
ssh "$host" "mkdir -p $data/snapshots"
# shellcheck disable=SC2086
rsync -a --delete --chmod=a+rX --bwlimit="${DEPLOY_BWLIMIT:-40000}" $link \
  "$snap/manifest.json" "$snap/corpus.sqlite" "$snap/lexical" "$snap/public" \
  "$host:$data/snapshots/$id/"

# 2. Switch the stack to it (compose reads deploy/server/.env) and wait for it to answer.
# The index directory goes to the container's user, which takes a lock file there.
ssh "$host" "chown -R 65534 $data/snapshots/$id/lexical &&
  cd $repo && git pull -q --ff-only &&
  printf 'SNAPSHOT_DIR=%s\nSNAPSHOT_ID=%s\n' $data/snapshots/$id $id > deploy/server/.env &&
  docker compose -f deploy/server/compose.yaml up -d --build --wait"
tries=0
until curl -fsS "$PUBLIC_API_BASE/health" | grep -q "\"$id\""; do
  tries=$((tries + 1))
  [ "$tries" -lt 30 ] || { echo "$PUBLIC_API_BASE/health does not report $id" >&2; exit 1; }
  sleep 2
done
echo "$PUBLIC_API_BASE serves $id"

# 3. Build the site against the same snapshot and publish it.
cd site
[ -d node_modules ] || npm ci
SAFETYPAGE_PUBLIC_DIR="$snap/public" SAFETYPAGE_API="$PUBLIC_API_BASE" npm run build:deploy
files=$(find dist -type f | wc -l | tr -d ' ')
echo "dist: $files files (Pages allows 20,000 a deployment)"
[ "$files" -lt 20000 ]
npx -y wrangler@4 pages deploy dist --project-name safetypage --branch main --commit-dirty=true
echo "live: $SITE_URL"
