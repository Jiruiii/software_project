#!/bin/bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo "Run with sudo." >&2; exit 1; }
cd "$(dirname "$0")"
base=/var/lib/classroom-deploy
account=classroom-deploy
as_deploy() { runuser -u "$account" -- env HOME="$base" GIT_TERMINAL_PROMPT=0 "$@"; }

if ! id "$account" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$base" --shell /usr/sbin/nologin "$account"
fi
install -d -m 0755 -o "$account" -g "$account" "$base"
if [[ ${1:-} == --key ]]; then
    as_deploy install -d -m 0700 "$base/.ssh"
    if [[ ! -f "$base/.ssh/id_ed25519" ]]; then
        as_deploy ssh-keygen -q -t ed25519 -N '' -C classroom-deploy -f "$base/.ssh/id_ed25519"
    fi
    # Published Ed25519 host key from GitHub's SSH key fingerprints documentation.
    printf '%s\n' 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' |
        as_deploy tee "$base/.ssh/known_hosts" >/dev/null
    as_deploy cat "$base/.ssh/id_ed25519.pub"
    exit
fi
[[ $# == 2 && $2 =~ ^[0-9a-f]{40}$ ]] || { echo "Usage: sudo bash install-update.sh <repository-url> <approved-main-SHA>" >&2; exit 2; }
case "$1" in
    https://github.com/Jiruiii/software_project.git|git@github.com:Jiruiii/software_project.git) ;;
    *) echo "Unexpected repository URL." >&2; exit 2 ;;
esac
sha=$2
# Check the remote and required release files before touching the running service.
remote=$(as_deploy git ls-remote --exit-code "$1" refs/heads/main)
[[ ${remote%%$'\t'*} == "$sha" ]] || { echo "GitHub main differs from the approved SHA." >&2; exit 1; }
systemctl is-active --quiet classroom.service
[[ ! -e "$base/active" || $(cat "$base/active") == manual ]] || { echo "Automatic deployment is already installed." >&2; exit 1; }
as_deploy git init --bare -q "$base/repo.git"
as_deploy git --git-dir="$base/repo.git" config remote.origin.url "$1"
as_deploy git --git-dir="$base/repo.git" fetch --depth=1 origin refs/heads/main
as_deploy git --git-dir="$base/repo.git" cat-file -e "$sha:deploy/update_classroom.py"

install -d -m 0755 /usr/local/lib/classroom-deploy /etc/systemd/system/classroom.service.d
install -m 0644 update_classroom.py /usr/local/lib/classroom-deploy/
install -m 0755 start-release.sh /usr/local/lib/classroom-deploy/
install -m 0644 classroom-update.{timer,service} /etc/systemd/system/
rule=$(mktemp)
trap 'rm -f "$rule"' EXIT
printf '%s\n' 'classroom-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart classroom.service' > "$rule"
visudo -cf "$rule"
install -m 0440 "$rule" /etc/sudoers.d/classroom-deploy
printf 'manual\n' | as_deploy tee "$base/active" >/dev/null
printf '%s\n' "$sha" | as_deploy tee "$base/bootstrap-commit" >/dev/null
printf '%s\n' '[Service]' 'ExecStart=' 'ExecStart=/usr/local/lib/classroom-deploy/start-release.sh' \
    > /etc/systemd/system/classroom.service.d/10-release.conf
systemctl daemon-reload
systemctl start classroom-update.service
systemctl enable --now classroom-update.timer
