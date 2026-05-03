"""Repo hygiene: build outputs and caches must stay out of review diffs.

Self-contained reduction of the W4-VERIFY agent branch (DEFERRED in
audit/REVIEW_NOTES_LOCAL_AGENT_2026-05-03.md) — bundles the
"no-tracked-build-output" check and the "gitignore actually catches
representative outputs" check in one file with no dependency on prior
stack commits.

Why both checks: the first catches the symptom (a build artifact already
tracked or staged), the second catches the cause (a .gitignore rule that
silently stopped matching after a path rename — e.g. `out 2/` vs `out/`).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Globs for already-tracked / already-staged build outputs. Patterns
# match git's pathspec syntax so they can be passed straight to
# `git ls-files`.
GENERATED_ARTIFACT_PATTERNS = [
    "frontend/.next/**",
    "frontend/out/**",
    "frontend/out 2/**",
    "frontend/out 3/**",
    "frontend/dist/**",
    "frontend/build/**",
    "frontend/*.tsbuildinfo",
    "**/__pycache__/**",
    "**/*.pyc",
    ".pytest_cache/**",
    "htmlcov/**",
]

# Representative paths that .gitignore should refuse to track. Each one
# is a real or plausible build output the project has produced before
# (the `out 2/`, `out 3/` variants exist because of past failed cleanups
# documented in the root .gitignore).
GENERATED_ARTIFACT_EXAMPLES = [
    "frontend/.next/build-manifest.json",
    "frontend/out/index.html",
    "frontend/out 2/index.html",
    "frontend/out 3/index.html",
    "frontend/dist/assets/app.js",
    "frontend/build/static/app.js",
    "backend/app/__pycache__/main.cpython-312.pyc",
    "frontend/tsconfig.tsbuildinfo",
    ".pytest_cache/v/cache/nodeids",
    "htmlcov/index.html",
]


def _git(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        **kwargs,
    )


def test_generated_artifacts_are_not_tracked_or_staged() -> None:
    """Build outputs may exist locally, but must not enter review diffs."""
    tracked = _git("ls-files", "--", *GENERATED_ARTIFACT_PATTERNS).stdout.splitlines()
    staged = _git(
        "diff", "--cached", "--name-only", "--", *GENERATED_ARTIFACT_PATTERNS
    ).stdout.splitlines()
    tracked_artifacts = sorted({p for p in tracked + staged if p})
    assert not tracked_artifacts, (
        "Generated artifacts are tracked or staged:\n"
        + "\n".join(tracked_artifacts)
    )


def test_generated_artifact_examples_are_gitignored() -> None:
    """Representative build and cache outputs must be ignored before staging.

    Uses `git check-ignore --no-index --stdin` so the test does not need
    the listed paths to actually exist on disk — it asks git directly
    "would you ignore this path if I tried to add it?".
    """
    result = _git(
        "check-ignore",
        "--no-index",
        "--stdin",
        input="\n".join(GENERATED_ARTIFACT_EXAMPLES) + "\n",
    )
    ignored_paths = {
        line.strip() for line in result.stdout.splitlines() if line.strip()
    }
    missing = [p for p in GENERATED_ARTIFACT_EXAMPLES if p not in ignored_paths]
    assert not missing, (
        "Generated artifact examples are not gitignored — fix the root "
        ".gitignore so each of these matches before staging:\n"
        + "\n".join(missing)
    )
