#!/usr/bin/env bash
# create-worktrees.sh
# Creates the codex + claude git worktrees pointing at branches under
# local-agents/. Idempotent: skips if a worktree already exists.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_root_git

mk_one() {
  local agent="$1" worktree branch
  worktree="$(agent_worktree "$agent")"
  branch="local-agents/$agent-base"

  if [ -d "$worktree" ]; then
    log "Worktree already exists: $worktree (skipping)"
    return 0
  fi

  cd "$REPO_ROOT"
  if git rev-parse --verify "refs/heads/$branch" >/dev/null 2>&1; then
    log "Branch $branch already exists; reusing"
    git worktree add "$worktree" "$branch"
  else
    log "Creating branch $branch from main + worktree at $worktree"
    git worktree add -b "$branch" "$worktree" main
  fi
  ok "Worktree ready: $worktree (branch $branch)"
}

mk_one codex
mk_one claude

echo ""
echo "Worktrees:"
git worktree list
