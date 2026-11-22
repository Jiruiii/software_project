#!/bin/sh
set -eu
base=/var/lib/classroom-deploy
version=$(cat "$base/active")
case "$version" in
    manual) release=/opt/classroom ;;
    *[!0-9a-f]*|'') exit 1 ;;
    *) [ "${#version}" -eq 40 ]; release="$base/releases/$version" ;;
esac
cd "$release"
exec .venv/bin/python app.py --public-origin "$PUBLIC_ORIGIN" \
    --firebase-config /etc/classroom/firebase.json \
    --sheets-service-account /etc/classroom/sheets.json \
    --db /var/lib/classroom/classroom.sqlite3
