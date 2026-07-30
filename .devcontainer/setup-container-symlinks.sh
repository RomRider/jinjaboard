#!/usr/bin/env bash
set -euo pipefail

# Creates deterministic symlinks inside /config so local workspace files are
# reflected in Home Assistant paths without bind mounts.
ensure_symlink() {
  local source="$1"
  local target="$2"

  mkdir -p "$(dirname "$target")"

  if [[ -L "$target" ]]; then
    local current
    current="$(readlink "$target")"
    if [[ "$current" == "$source" ]]; then
      return
    fi
  fi

  if [[ -e "$target" || -L "$target" ]]; then
    rm -rf "$target"
  fi

  ln -s "$source" "$target"
}

if [[ "$#" -lt 1 ]]; then
  echo "Usage: $0 <workspace-root>" >&2
  exit 1
fi

workspace_root="$1"

ensure_symlink "$workspace_root" "/config/www/workspace"
ensure_symlink "$workspace_root/.devcontainer/test" "/config/test"
ensure_symlink "$workspace_root/.devcontainer/test/configuration.yaml" "/config/configuration.yaml"
ensure_symlink "$workspace_root/custom_components/jinjaboard" "/config/custom_components/jinjaboard"

echo "Symlink setup complete."
