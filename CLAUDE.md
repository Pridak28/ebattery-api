# CLAUDE.md

Project: battery-analytics-pro

Claude should act as a senior full-stack engineer, product architect, and BESS analytics reviewer.

Priorities:
1. Make the app run locally.
2. Fix dependencies, imports, TypeScript, lint, build, and runtime errors.
3. Improve UI/UX for a serious investor-grade BESS analytics dashboard.
4. Review battery revenue, arbitrage, BESS, chart, and financial logic.
5. Improve validation, empty states, loading states, and error states.
6. Add or improve tests where reasonable.
7. Never push to a remote (`git push` is forbidden — `LOCAL_AGENT_PUSH_BRANCHES=0` in `tools/local-agents/lib.sh` enforces this for the local-agent loop). This repo currently has no `git remote` configured; never add one without explicit user instruction.
8. Never deploy. No production push, no Netlify/Vercel/Render/etc. trigger, no infrastructure changes. The app runs locally only.
9. Work on a review branch (`review/<topic>-YYYYMMDD` or a `local-agents/...` task branch). Fast-forward `main` locally **only after**: (a) backend pytest is fully green on the review branch tip, (b) frontend `tsc --noEmit` + `lint` + `build` are clean, (c) all changes have been reviewed and recorded in an `audit/REVIEW_NOTES_*.md` file. Allowed: `git merge --ff-only <review-branch>`. Forbidden on main: `--no-ff`, `--force`, `git reset --hard`, `git rebase` of commits already on main, amending commits already on main. A clean fast-forward is the local equivalent of merging a PR; only that form is allowed.
10. Never bypass any of these rules with `--no-verify`, `--force`, or by editing this file to weaken them without explicit user instruction.
