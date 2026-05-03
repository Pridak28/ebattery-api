# Local-agent run review — 2026-05-03

Reviewer: Claude
Review branch: `review/local-agent-results-20260503` from `main` @ `644c905`.

## Scope

- Orchestration commits `0d703fd..644c905` on `main` (10 commits)
- 5 priority agent branches per the user's review plan + 1 interrupted Claude docs branch
- No deploys, no pushes, no merge to main, no agent restarts

## Orchestration verification — main `0d703fd..644c905`

Verified safe via static checks:
- `bash -n tools/local-agents/*.sh` → all 11 scripts syntactically clean.
- `git diff --check` → no whitespace errors / conflict markers.
- `grep` for `git push|git merge main|deploy` in scripts → no active calls (only one match in a doc string for `data-pipeline` role instructions: "deploy-safe processed artifacts").
- `LOCAL_AGENT_PUSH_BRANCHES` default = `0` confirmed in `lib.sh`.

Commit sequence reviewed:
- `0cecb9d` failover when one agent runs out of tokens
- `43ed728` non-interactive CLI invocation (`codex exec` / `claude -p`)
- `5580992` codex exec doesn't accept `-a` (already non-interactive)
- `825d15c` role provider takeover (schema v2)
- `ce6add3` master task refill loop
- `cfa7b41` evidence-based refill
- `a7ac485` smart refill report quoting
- `f57b2fd` ignore smart refill runtime reports
- `05c9fd0` keep loop alive on provider failover
- `644c905` allow restart with runtime queue state

**Verdict**: orchestration on `main` is safe. No further action needed.

## Branch reviews

### Branch 1: `local-agents/20260503T101132Z/codex-t-smart-20260503t101949z-w1-fallbacks` — DEFERRED

- HEAD commit: `b129169` "Smart master: inspect one hardcoded/fallback/mock path"
- **Task-local diff (HEAD only)**: 3 files / 63 insertions / 7 deletions
  - `backend/app/api/routes/fr.py`: add optional `capacity_mwh` query param to `/optimal-bids`
  - `backend/app/services/fr_service.py`: accept `capacity_mwh`, replace hardcoded 30, add ValueError guard, add warning when default is used
  - `backend/tests/test_services_edge_cases.py`: 1 updated + 1 new test for explicit capacity
- **Cumulative diff vs main**: 62 files / 4409+/1015− — branch is **stacked** on many earlier task branches.
- **Verdict**: ACCEPT IN ISOLATION but **DEFERRED for cherry-pick**.
  - The clean task-local change is good (small, scoped, backward-compat, tested).
  - Cherry-pick fails: depends on a `warnings: List[str]` accumulator and `activation_energy_basis` variable plus `assumptions` response field that don't exist in `main`. Earlier commits in the chain added them.
  - **Recommendation**: review the entire stack `local-agents/20260502T201304Z/codex-t-smart-*` as a unit, OR craft a hand-written reduction commit that ONLY introduces the `capacity_mwh` parameter (no warnings infrastructure).
- No bankable/live/guaranteed claims introduced.

### Branch 2: `local-agents/20260503T101132Z/claude-t-master-20260503t112225z-w5-frontend` — ACCEPTED, cherry-picked as `6496ef8`

- Source commit: `311339e` "claude/T-MASTER-20260503T112225Z-W5-FRONTEND: reframe dashboard onboarding 'Live data' tour step…"
- **Task-local diff**: `frontend/app/page.tsx` / +26 / −2 (one tour-step copy block plus an inline audit comment).
- **Verdict**: ACCEPTED. Cherry-pick clean (`git cherry-pick -x 311339e` → `6496ef8` on review branch).
- **Why it's safe**:
  - Removes overconfident `'Live data'` title and the blanket `'All numbers are backed by real Romanian market data, refreshed daily.'` claim.
  - Replaces with `'Market data backing'` (matching `DataFreshnessBadge` heading) and a description that names `/api/v1/data/manifest`, names the OPCOM PZU + DAMAS aFRR datasets, calls out the `ILLUSTRATIVE` summary cards above the badge, and routes the investor to the simulators for real numbers.
  - Aligns with the W1 / W2 unsafe-wording downgrade of `LIVE` chips on `/investment` (`3275e29`) and global Sidebar `Live Data` (`5a913e1`).
  - Branch's commit message reports `npx tsc --noEmit` clean, `next lint` clean, `pytest -q` 364 passed.
- **Independent re-check**: `git diff --check` clean on the cherry-picked commit. No new bankable / guaranteed wording introduced; the reframed copy adds the qualifier `ILLUSTRATIVE` instead.

### Branch 3: `local-agents/20260503T101132Z/claude-t-master-20260503t112225z-w5-feature` — DEFERRED

- HEAD commit: `14585ae` "claude/T-MASTER-20260503T112225Z-W5-FEATURE: deterministic scenario fingerprint shared by cashflow CSV preamble and scenario JSON export"
- **Task-local diff (HEAD only)**: 4 files / 482 insertions
  - `frontend/lib/scenarioFingerprint.ts` — new (327 lines, pure-function FNV-1a-64, cross-runtime, no native deps; sanity-checked against published "a" → `af63dc4c8601ec8c` vector).
  - `frontend/lib/cashflowCsv.ts` — +15 lines to print the fingerprint in the CSV preamble.
  - `frontend/lib/scenarioJson.ts` — +28 lines to embed the fingerprint in the JSON export.
  - `docs/SOURCE_CONFIDENCE_AUDIT.md` — +112 lines (new audit section).
- **Cumulative diff vs main**: stacked on many earlier branches (frontend `cashflowCsv.ts`, `scenarioJson.ts` in their current form, plus the runbook itself).
- **Verdict**: ACCEPT IN ISOLATION but **DEFERRED for cherry-pick**.
  - The fingerprint module is well-engineered (deterministic, sorted-key canonical form, float rounded to 6 decimals, exported_at / version excluded) and the LP-analyst use case is clean.
  - Cherry-pick would fail: `frontend/lib/cashflowCsv.ts` and `frontend/lib/scenarioJson.ts` do not exist on main in the form the diff edits, and `docs/SOURCE_CONFIDENCE_AUDIT.md` does not exist on main at all.
  - **Recommendation**: review the W2/W4 feature stack (`*-w2-feature`, `*-w4-feature`, `*-w5-feature`) as a unit, since the fingerprint only earns its keep once both the CSV preamble (W2) and the scenario JSON export (W2 follow-up) and the bankability verdict (W4) are also landed.
- No bankable/live/guaranteed claims introduced.

### Branch 4: `local-agents/20260503T101132Z/codex-t-master-20260502t225148z-w4-verify` — DEFERRED

- HEAD commit: `d15826a` "codex/T-MASTER-20260502T225148Z-W4-VERIFY: add or improve one test/build/static check…"
- **Task-local diff (HEAD only)**: `backend/tests/test_generated_artifacts.py` / +29 / −0
  - Adds `GENERATED_ARTIFACT_EXAMPLES` list (10 representative paths: `frontend/.next/...`, `frontend/out 2/...`, `frontend/dist/...`, `__pycache__`, `.tsbuildinfo`, `.pytest_cache`, `htmlcov`).
  - Adds `test_generated_artifact_examples_are_gitignored()` which pipes the list to `git check-ignore --no-index --stdin` and asserts every path is reported as ignored.
- **Verdict**: ACCEPT IN ISOLATION but **DEFERRED for cherry-pick**.
  - The test is small, deterministic, and cross-checks the `.gitignore` against a concrete enumeration of representative build outputs — exactly the "verification" role the task asked for.
  - Cherry-pick would fail: the base file `backend/tests/test_generated_artifacts.py` does not exist on `main` (`git ls-tree main -- backend/tests/test_generated_artifacts.py` empty). It was added by an earlier W4 verify commit in the same stack.
  - **Recommendation**: review the `*-w4-verify` stack and the introduction of `test_generated_artifacts.py` as a unit, OR hand-write a self-contained file that includes both the original list test and the new `git check-ignore` test in a single commit.
- No bankable/live/guaranteed claims introduced. The new test only inspects `.gitignore` behavior.

### Branch 5: `local-agents/20260503T101132Z/codex-t-master-20260502t225154z-w2-data` — DEFERRED

- HEAD commit: `2913bdd` "codex/T-MASTER-20260502T225154Z-W2-DATA: strengthen one data manifest, source-kind, freshness, duplicate, outlier, or public-vs-settlement check"
- **Task-local diff (HEAD only)**: 4 files / 117 insertions / 4 deletions
  - `backend/app/market_data/manifest.py` (+27 / −2): adds `_unique_string_values` and `_unique_bool_values` helpers, uses `_missing_or_blank_count` inside `assert_artifact_provenance_matches_manifest`.
  - `backend/app/market_data/quality.py` (+32 / −2): related quality helpers.
  - `backend/tests/test_manifest_unit.py` (+40): new tests for manifest helpers.
  - `backend/tests/test_quality_extra.py` (+22): new tests for quality helpers.
- **Verdict**: ACCEPT IN ISOLATION but **DEFERRED for cherry-pick**.
  - The change is on-task (provenance-matching helpers + tests) and the test additions look thorough.
  - Cherry-pick attempted: `git cherry-pick -x 2913bdd` produced 4-file conflict (UU on all four files). The branch references `assert_artifact_provenance_matches_manifest` and `_missing_or_blank_count`, which `git show main:backend/app/market_data/manifest.py | grep -c "assert_artifact_provenance_matches_manifest"` confirms do **not** exist on `main`. Both were added by earlier branches in the W2-DATA stack.
  - Cherry-pick aborted cleanly with `git cherry-pick --abort`.
  - **Recommendation**: review the entire W2-DATA stack as a unit, OR craft a hand-written reduction commit that introduces a self-contained pair of helpers + matching tests against the actual `main` shape of `manifest.py` / `quality.py`.
- No bankable/live/guaranteed claims introduced.

### Branch 6: `local-agents/20260503T101132Z/claude-t-master-20260503t112225z-w5-docs` — DEFERRED

- Branch state at start of review: HEAD `844c0d4` plus uncommitted edit to `docs/SOURCE_CONFIDENCE_AUDIT.md` (+222 / −4).
- The uncommitted edit was the W5-DOCS pass: adds `§11 Investor-facing artifact: dashboard onboarding tour step 2`, with §11.1 invariants (six MUST conditions), §11.2 reviewer greps (eight presence + negative checks), §11.3 audit-trail entry, §11.4 rationale. Updates §7 and §10.3 cross-reference lists to enumerate §11.3.
- **Action taken on the docs branch**:
  - Committed the dangling edit on the docs branch as `c2403d0` so it is not lost. (Per the user's plan: "If good: commit it on that branch, then cherry-pick into the review branch.") The commit lives only on `local-agents/20260503T101132Z/claude-t-master-20260503t112225z-w5-docs` and was not pushed.
- **Verdict**: ACCEPT IN ISOLATION but **DEFERRED for cherry-pick**.
  - The §11 addition is high-quality investor-protection documentation: it locks in the exact wording invariants of the W5-FRONTEND change cherry-picked as Branch 2 (`6496ef8`), names every grep a reviewer should run on a future copy refresh, and ties the tour into the same `wording_audit` JSONL trail used by §7-§10.
  - Cherry-pick fails for the same stack reason as Branches 1, 3, 4, 5: `docs/SOURCE_CONFIDENCE_AUDIT.md` does not exist on `main` (`git ls-tree main -- docs/SOURCE_CONFIDENCE_AUDIT.md` empty). The §11 addition presupposes §1-§10. `git cherry-pick -x c2403d0` produced a `modify/delete` conflict and was aborted.
  - **Recommendation**: review the `*-w5-docs` (and the broader audit-doc) stack as a unit, OR hand-write a single self-contained `SOURCE_CONFIDENCE_AUDIT.md` that includes only §1-§3 (manifest scaffolding) + §11 (the tour invariants for the cherry-picked Branch 2 change), so the runbook lands in tandem with the code it audits.
- The committed dangling edit (`c2403d0`) is not on the review branch and is not on `main`. It survives only on the local-agent branch — it can be discarded later by deleting the branch if desired, or kept as reference for the recommended stack-review.

## Validation results

Run from the review branch tip (cherry-pick of Branch 2 is the only landed change beyond the orchestration commits already on main).

### Tests ran on the cherry-picked surface

- `python3 -m py_compile backend/app/services/fr_service.py backend/app/api/routes/fr.py backend/tests/test_services_edge_cases.py` — see live run below.
- `cd frontend && npx tsc --noEmit` — see live run below.
- `cd frontend && npm run lint` — see live run below.
- `cd frontend && npm run build` — see live run below.
- `git diff --check && git status --short` — see live run below.

(Detailed pass/fail and any environmental blockers — Python/NumPy arch mismatch in particular — are recorded in the validation appendix at the bottom of this file once the commands have been run.)

### Validation appendix — actual results on review branch tip

Review branch HEAD: `6496ef8` (one commit beyond `main` @ `644c905`).
Cleanliness: `git diff --check` clean. `git status --short` shows only the new `audit/REVIEW_NOTES_LOCAL_AGENT_2026-05-03.md` (this file).

| Command | Result |
|---|---|
| `python3 -m py_compile backend/app/services/fr_service.py backend/app/api/routes/fr.py backend/tests/test_services_edge_cases.py` | PASS (no output, exit 0) |
| `cd backend && PYTHONPATH=. arch -arm64 /usr/local/bin/python3 -m pytest tests/test_market_data_pipeline.py tests/test_manifest_unit.py` | PASS — 33 passed in 0.11 s, 1 unrelated pandas date-format UserWarning |
| `cd backend && PYTHONPATH=. arch -arm64 /usr/local/bin/python3 -m pytest -q --ignore=tests/test_property_invariants.py` | PASS — 345 passed in 88.16 s, 3 unrelated warnings (pandas date format, `datetime.utcnow()` deprecation) |
| `cd frontend && npx tsc --noEmit` | PASS (no output, exit 0) |
| `cd frontend && npm run lint` | PASS — `✔ No ESLint warnings or errors` |
| `cd frontend && npm run build` | PASS — `✓ Compiled successfully`, 9/9 static pages generated; `/` page bundle 10.7 kB / 228 kB First Load JS (Branch 2's tour-step diff +24 net source lines did not regress bundle size meaningfully) |

Environmental notes:
- `tests/test_property_invariants.py` excluded from the full pytest run because the optional `hypothesis` dependency is not installed locally. Same exclusion the W5-FRONTEND commit message reports — not a regression introduced by this review.
- The `arch -arm64 /usr/local/bin/python3` invocation is required because the system Python is universal2 and pandas/NumPy on this host are arm64-only; running plain `python3 -m pytest` triggers the architecture mismatch the user's plan flags.
- All 345 backend tests passed; no Python/NumPy arch-mismatch errors observed when the `arch -arm64` prefix is used.

**Conclusion**: the review branch (one cherry-picked commit beyond `main`) is green across compile / pytest / tsc / lint / build. Branch 2 can be safely fast-forwarded into `main` if the human reviewer chooses to. No further validation needed before that decision.

## Cherry-pick summary

| Branch | Verdict | SHA on review branch |
|---|---|---|
| 1 — fallbacks (codex-t-smart…w1-fallbacks) | DEFERRED | — |
| 2 — frontend tour (claude…w5-frontend) | ACCEPTED | `6496ef8` |
| 3 — scenario fingerprint (claude…w5-feature) | DEFERRED | — |
| 4 — verify gitignore (codex…w4-verify) | DEFERRED | — |
| 5 — data provenance helpers (codex…w2-data) | DEFERRED | — |
| 6 — onboarding-tour audit docs (claude…w5-docs) | DEFERRED | — |

**Net change to the review branch beyond `main`**: 1 commit (`6496ef8`), 1 file, +26 / −2.

**Pattern**: 5 of 6 priority branches are stacked on infrastructure (response fields, helper functions, test files, runbook scaffolding) added by earlier commits in their respective task chains. Only Branch 2 was a clean isolated change. To land any of Branches 1, 3, 4, 5, 6, the recommended path is **stack-level review** (review the whole `local-agents/20260502T201304Z/...-w<N>-<role>` chain as one unit before cherry-picking the chain tip), not piecemeal cherry-picking.

## Hard limits honored this run

- `LOCAL_AGENT_PUSH_BRANCHES=0` — no remote pushes attempted or executed.
- No `git merge` into `main`. The review branch lives off `main`; only the human can decide to fast-forward.
- No worker / master / loop processes were started by this review.
- The `reports/local-agents/queue/tasks.json` runtime file present at review start was stashed (`git stash push --keep-index --include-untracked -m "runtime-tasks-json-during-review-20260503T122337Z"`) so it does not pollute the review-branch diff. To restore: `git stash list | grep runtime-tasks-json-during-review-20260503T122337Z` then `git stash pop <id>`.
- Branch 6's dangling edit was committed on its own branch (`c2403d0`) and not propagated anywhere else.

## Next steps for the human reviewer

1. `git checkout review/local-agent-results-20260503` and inspect `git log main..HEAD` (one commit beyond orchestration: `6496ef8`).
2. Decide whether to fast-forward `main` to the review branch (lands only Branch 2's tour-copy reframe), or to defer.
3. For the five DEFERRED branches: pick the highest-value one (Branch 6 docs is the strongest candidate since it documents an already-accepted code change; Branch 4 verify is the smallest delta; Branch 5 data is the most substantive) and either (a) review its stack chain, or (b) commission a hand-written reduction commit against current `main`.
4. Optionally `git pop` the runtime tasks.json stash to keep the local-agent loop restartable from where it stopped.
