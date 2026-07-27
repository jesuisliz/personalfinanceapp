---
name: build-phase
description: Design and build a new CLAUDE.md roadmap phase (or any substantial multi-file feature) in this app, from planning through documentation. Use whenever the user says "let's do phase N", "build the next phase", or asks for a feature big enough to need real design decisions (new data, new UI surface, new architecture) rather than a small tweak.
---

# Build a Roadmap Phase

This project's phases (see `CLAUDE.md`) have all followed the same shape once Phase 3 onward established the pattern. Phase 3 skipped writing a design doc and that was flagged as a gap later — every phase since writes one. Follow these steps in order.

## 1. Ground yourself in what's actually being asked

- Read the phase's bullet list in `CLAUDE.md`'s Roadmap.
- Read `docs/PROJECT_CONTEXT.md`'s Vision / example questions / Definition of Success for anything relevant to this phase — CLAUDE.md's roadmap items are terse; PROJECT_CONTEXT.md has the concrete "why."
- Read `docs/hld_claude.md` §6 (Roadmap Alignment & Success Criteria) — the phase may already have a stub criteria list from an earlier planning pass. Don't re-derive it from scratch; extend/confirm it.

## 2. Look for what already exists before designing anything new

This app has a consistent per-domain split: `app/<domain>/aggregates.py` (pure business logic) + `app/routers/<domain>.py` (thin HTTP layer) — see `app/dashboard/`, `app/chat/`, `app/planning/`. Before writing a new calculation:
- Check whether an existing aggregate function already computes it, or most of it. Phase 5's scenario analysis reused Phase 4's `estimate_category_reduction_savings` unchanged rather than reinventing it — that reuse is the norm, not an exception.
- Check whether the chatbot (Phase 4+) should get a matching tool wrapper so the same calculation is answerable both via a dedicated UI tab and in natural language — one source of truth, multiple surfaces, per the pattern in `app/chat/tools.py`.

## 3. Find the "does the app actually have this data" question — don't assume it does

Before designing calculations, ask explicitly: is every input to this feature actually derivable from what's already imported? Phase 5's financial runway needed a current balance, and CSV imports are bounded date ranges, never full account history — the app could not derive this, so it became explicit manual user input instead of a guess. Look for this class of gap on every new phase; it's the single most likely place "never guess financial data" (`CLAUDE.md`) gets violated by accident.

## 4. Plan mode: ask before designing

Use `EnterPlanMode`. Ask 3-5 targeted clarifying questions via `AskUserQuestion` for genuine judgment calls only (data model shape, UI placement, scope boundaries) — each with a recommended default, not an open-ended "what do you want." Past examples worth the ask: model choice/cost tradeoffs, whether history/state persists or is ephemeral, whether a feature is its own concept or reuses an existing one (e.g. "is a vacation its own thing, or just a labeled savings goal?" — it became the latter).

## 5. Write the plan with these sections

- **Context** — why this phase needs what it needs, referencing the CLAUDE.md/PROJECT_CONTEXT.md source and any "does the app have this data" findings from Step 3.
- **Data model** (only if new persisted state is needed — most phases don't; state explicitly when one doesn't, e.g. "no new tables, in-memory only" is itself a decision worth recording).
- **Backend** — new/reused aggregate functions, router endpoints, schemas, chat tool wrappers if applicable.
- **Frontend** — new tab/component, reusing existing formatting/stat-tile/table patterns already in `Dashboard.tsx`/`Planning.tsx` rather than inventing new UI conventions per phase.
- **Documentation** — commit up front to writing `docs/lld_phaseN_claude.md` once built (see Step 8) — do not defer or skip this even if it feels like it can wait; that's exactly what happened with Phase 3 and had to be caught later.
- **Explicit Non-Goals** — what's deliberately out of scope this phase, and why.
- **Verification** — full test suite, `tsc -b` + `oxlint`, a live walkthrough, and an independent verification pass (see the `verify-financial-number` skill) for at least one computed value per new calculation.

## 6. Track implementation with tasks

Use `TaskCreate`/`TaskUpdate` — one task per backend module, per test file, per frontend component, plus dedicated tasks for "verify" and "write docs." Mark each in_progress before starting, completed only once actually done (tests passing, not just code written).

## 7. Build, then verify for real

- Run the full backend test suite and frontend `tsc -b`/`oxlint` fresh after finishing, not just incrementally — confirm the count of passing tests explicitly (e.g. "92 → 114") rather than just "tests pass."
- Do a live walkthrough in the browser, not just an API-level check.
- For every new financial calculation, independently verify at least one real value — see the `verify-financial-number` skill for how, including the dev-server gotchas that make this trickier than it sounds.
- Test the *honest-refusal* case, not just the happy path: if the feature can say "not enough data" / "not on track" / "already met," deliberately trigger that state and confirm it's handled, not just the easy positive example.
- If verification required creating real records (a goal, a balance, a transaction) in the actual app database, delete/reset them afterward — this is the user's live personal app, not a disposable test environment.

## 8. Update documentation and memory to match what was actually built

- Write `docs/lld_phaseN_claude.md`, matching the structure of the existing `lld_phase2_claude.md`/`lld_phase4_claude.md`/`lld_phase5_claude.md` (Architecture, Data Model, API, Success Criteria — filled in with real verified results, not aspirational language, Non-Goals).
- Update `docs/hld_claude.md` §6's entry for this phase from its prior status to complete, with each success criterion annotated with what was actually confirmed. Update the architecture diagram in §3 if a new frontend surface was added.
- Write or update a `phaseN_status` memory file (see existing `phase3_status.md` through `phase5_status.md` for the level of detail expected: what was built, key decisions and why, what was independently verified with the actual numbers, any gotchas hit). Add a one-line pointer to `MEMORY.md`'s index.
- If a new environment/workflow gotcha was discovered, add it to the consolidated `dev_server_gotchas.md` memory rather than duplicating it inside the phase-status file.
