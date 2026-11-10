#!/bin/zsh
# m.sh <name> <url> <width> '<expr>' [--click sel] : runs measure.mjs, saves to out/<name>.json
mkdir -p out
name=$1; shift
node /Users/noahairmet/development/tools/ui-check/lib/measure.mjs "$@" > out/$name.json 2> out/$name.err
echo "== $name"; cat out/$name.json | head -c 6000; echo
