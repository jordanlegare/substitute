# Bank of Canada Research Policy Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated stochastic Bank of Canada policy-path simulator with Monte Carlo common random numbers, institutional-risk constraints, mandate-first optimization, stress testing, reporting, CLI support, and dedicated tests/CI.

**Architecture:** Build a standalone `boc_policy/` package that shares only the repository's NumPy dependency. Candidate policy paths are simulated with identical seed vectors, filtered by institutional-risk limits, and only then ranked by a mandate loss that excludes Bank accounting outcomes. Existing ALD execution paths remain untouched.

**Tech Stack:** Python 3.10+, NumPy, pytest; optional pandas/matplotlib for fan charts.

**Spec:** `docs/superpowers/specs/2026-09-06-boc-policy-research-engine-design.md`

## Global Constraints

- Python 3.10+.
- Core runtime adds no dependency beyond NumPy.
- pandas/matplotlib are optional under a `boc` extra and must be lazily imported.
- All stochastic transitions consume an explicit `numpy.random.Generator` supplied by the caller.
- Candidate comparisons use common random-number seed vectors.
- Bank accounting metrics are institutional-risk constraints and never direct mandate-loss terms.
- An infeasible path is never selected merely because it has a lower mandate loss.
- Existing ALD modules and execution paths remain unchanged.

---

### Task 1: Core state, transition, and accounting engine

**Files:** `boc_policy/models.py`, `boc_policy/engine.py`, `boc_policy/__init__.py`, `tests/test_boc_policy.py`

- [x] Write failing tests for inflation weights, policy path behavior, accounting identities, RNG isolation, and deterministic simulation.
- [x] Verify RED with the missing package.
- [x] Implement the core models and transition engine using explicit RNG plumbing.
- [x] Verify GREEN with the targeted tests.

### Task 2: Risk envelope and mandate-first optimization

**Files:** `boc_policy/risk.py`, `boc_policy/optimize.py`, `tests/test_boc_policy.py`

- [x] Write failing tests for probability summaries, profile limits, accounting-independent mandate loss, feasible-only selection, candidate determinism, and common-seed reuse.
- [x] Verify RED for missing risk/optimizer behavior.
- [x] Implement risk summaries, exact profiles, mandate loss, candidate generation, evaluation, and feasible-only selection.
- [x] Verify GREEN.

### Task 3: Stress testing, reporting, CLI, and optional plotting

**Files:** `boc_policy/stress.py`, `boc_policy/report.py`, `boc_policy/cli.py`, `boc_policy/plotting.py`, `tests/test_boc_policy.py`

- [x] Write failing tests for stress behavior, profile comparison, report boundary language, shared stress seeds, CLI JSON, plotting import behavior, and logging configuration.
- [x] Verify RED for missing behavior.
- [x] Implement stress/report/CLI/plotting/logging behavior.
- [x] Verify GREEN.

### Task 4: Packaging, documentation, and CI integration

**Files:** `pyproject.toml`, `docs/boc-policy-research.md`, `.github/workflows/boc-policy.yml`, design spec, implementation plan.

- [x] Add packaging metadata and validate it with `tomllib`.
- [x] Add research documentation with architecture, usage, boundaries, and limitations.
- [x] Add path-filtered GitHub Actions verification for tests, compile, and CLI smoke execution.
- [x] Run local package tests and bytecode compilation.

### Task 5: Final verification and pull request

- [x] Run `python -m pytest -q tests/test_boc_policy.py && python -m py_compile boc_policy/*.py`.
- [x] Run a deterministic CLI JSON smoke command.
- [ ] Push the verified files to `feature/boc-policy-research-engine`.
- [ ] Review the remote diff for scope, accidental ALD changes, and spec coverage.
- [ ] Open a PR against `main` with verification evidence and scientific limitations.
- [ ] Inspect PR checks/status and report any remaining CI uncertainty accurately.
