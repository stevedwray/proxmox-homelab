#!/usr/bin/env bash
# Installs this repo's custom (non-pre-commit-framework) git hooks by
# symlinking tracked scripts under scripts/git-hooks/ into .git/hooks/.
# Idempotent; refuses to clobber a hook it didn't install itself.
#
# The pre-commit/pre-push hooks are managed separately by the `pre-commit`
# framework (see .pre-commit-config.yaml, `pre-commit install`) -- this
# script only handles hook types that framework doesn't cover, currently
# just post-commit.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

install_hook() {
  local hook_type="$1"
  local src="$REPO_ROOT/scripts/git-hooks/${hook_type}-docs-reindex.sh"
  local dst="$REPO_ROOT/.git/hooks/${hook_type}"

  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "Refusing to overwrite existing, non-symlink $dst -- merge manually if you want both." >&2
    return 1
  fi

  chmod +x "$src"
  ln -sf "$src" "$dst"
  echo "Installed: $dst -> $src"
}

install_hook post-commit
