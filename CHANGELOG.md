# Changelog

All notable changes to Intent OS are documented here.

---

## v0.6.0 (2026-07-24)

### Agent Profile — Agent as a Person

- **Agent dataclass expanded** — Added `persona` (role description), `traits` (personality characteristics), and `avatar` (emoji/icon) fields. An agent is now more than an ID — it has identity, personality, and character.
- **`agent get` person-card output** — The `agent get` command now shows a complete character card: role, traits, status, capabilities, experience summary, execution history, cost overview, and recent runs — all in one view. Identity + Execution + Experience layers now converge in a single profile.
- **`agent update --traits +/-`** — Traits can be appended (`+cautious`), removed (`-aggressive`), or replaced (no prefix) via comma-separated syntax.
- **`agent create --persona --traits --avatar`** — New agent creation now supports role, traits, and avatar in one command.
- **SPEC-0009: Agent Asset Model** — First draft of the Agent Asset standard, defining the profile format as the foundation for portable `.agent` packages.
- **CLI --version updated** — `intent-os --version` now shows 0.6.0.

### Agent Store

- Added `set_persona()`, `add_trait()`, `remove_trait()` methods to `AgentStore`.
- Schema migration for existing databases (persona, traits, avatar columns).

---

## v0.5.2 (2026-07-24)

### Fixes

- **README test badge** — 721 → 824 (matches actual test count)
- **README database path** — `events.db` → `intent.db` (unified DB name)
- **Git history cleanup** — Remove CLAUDE.md, GUIDE.md, STRATEGY.md from git history (local-only files)

---

## v0.4.1 (2026-07-22)

### Bug Fixes

- Bundle example manifests (translate, code_review, sentiment_analyze, etc.) in pip package so `intent-os run <name>` works after `pip install intentos`
- Fix `pip install intent-os` leftover in demo output (now `pip install intentos`)
- Inconsistent pip install commands across README and demo

### PyPI

- Package renamed from `intent-os` to `intentos` (PyPI name conflict)
- v0.4.1 published with correct bundled examples

---

## v0.4.0 (2026-07-22)

### Highlights

- **Documentation site** — MkDocs + Material 14-page site with auto-deploy to Pages
- **CLI UX overhaul** — bare capability names, inline parameters, SimulatedAdapter fallback
- **Ask degraded mode** — graceful experience when no LLM provider is available

### Engine

- Fix `AutoProvider.name` delegating to underlying provider (was returning `"auto"`)
- Upgrade Ollama default model from `llama3.2:1b` to `llama3.2:latest` (3.2B)
- Skip cloud adapters when credentials are not set (cleaner `setup_executor`)
- Add explicit R1 violation warning to Scheduler docstring
- Mark all `except: pass` blocks with explanatory comments

### CLI

- `intent-os run` now accepts bare capability names (e.g. `translate`) — resolves from built-in manifests
- Add `--param`/`-p key=value` syntax for inline input parameters
- Add positional `text` argument (maps to the `text` field automatically)
- Add `SimulatedAdapter` fallback when no real runtime adapter is available
- `intent-os demo --auto` — non-interactive mode for CI/previews
- `intent-os ask` graceful degraded mode: when no LLM is available, shows built-in capability list + install guide
- Capability discovery: unknown capability names now list all built-in options with descriptions
- Add `list_builtin_capabilities()` helper to `commands/helpers`

### Docs Site

- Full 14-page MkDocs + Material documentation site
- Homepage with value anchor ("Your AI capabilities should not be locked in")
- Quickstart, Guide (manifest, runtime, workflow, security), CLI reference, Examples
- GitHub Actions CI for auto-deploy to GitHub Pages
- Custom domain CNAME (`intent-os.org`)

### Packaging

- Version bump 0.3.0 → 0.4.0
- Fix Homepage URL (`intent-os` → `X-code-sourse`)
- Add Source and BugTracker URLs; add keywords for PyPI discovery
- Switch to SPDX license expression; remove deprecated classifiers
- Delete stale `setup.py` (v0.2.0, conflicted with pyproject.toml)
- Add `publish.yml`: build + twine check + Test PyPI and production PyPI jobs

### Tests

- Test coverage: 689 passed, 8 skipped, 0 failing (was 682+16skip+7fail)
- CLI tests updated for new `run`/`demo` behavior (39 CLI tests passing)
- Ask integration tests fully passing with Ollama 3.2B

---

## v0.3.0 (2026-07-21)

### Highlights

- **Ask Command** — natural language capability execution
- **Security Model** — 120 tests, Policy Engine, SecurityManager integration
- **Data-Driven Planner** — analytics-driven template/capability selection

### Engine

- Implement AskSession: classify → resolve → extract → execute → summarise pipeline
- Implement multi-turn REPL mode with adapter switching (e.g. `用 OpenAI`)
- Implement LLM Provider abstraction (Ollama, OpenAI, Anthropic, Auto)
- Implement full Security Model (SPEC-0004): Policy, PolicyStore, SecurityManager
- Integrate SecurityManager into Executor with ALLOW/DENY/REQUIRE_REVIEW
- Implement Data-Driven Planner: analytics-driven template and capability ranking
- Implement multi-plan enumeration with CostModel estimates
- Add Cost Model with default values + historical weighted estimation
- Add Evolution Loop: analysis → suggestion → auto-apply with human approval
- Complete EventType taxonomy for all modules

### CLI

- 16 commands: validate, run, compare, list, registry, security, event, analytics,
  workflow, mcp-server, import, export, quickstart, evolution, ask, demo
- Zero-config demo (`intent-os demo`)
- Interactive and single-query Ask modes
- Security policy management (apply/evaluate/audit)
- Workflow plan/run/optimize
- MCP Server management (SSE transport)

### Adapters

- OpenAI, Anthropic, Ollama, OpenRouter, GitHub Models
- Cross-runtime comparison (`intent-os compare`)
- L1–L4 compatibility tests (42 tests)

### Examples

- 6 built-in manifests: translate, text_summarize, code_review, sentiment_analyze,
  data_extract, image_analyze

### Tests

- 681 tests total (21 test files)
- Cross-runtime automation, security integration, Ask pipeline

---

## v0.2.0 (2026-07-20)

Initial release.

### Core

- Capability Manifest format (SPEC-0001) with YAML parser
- Workflow DAG model with execution semantics (SPEC-0002)
- Event system with SQLite-backed Event Store (SPEC-0003)
- TF-IDF semantic search engine
- Capability Registry with SQLite persistence
- Simulated adapter for testing

### CLI

- Basic CLI framework with argparse
- validate, run, compare, list, registry commands

### Infrastructure

- CI with Python 3.10/3.11/3.12 matrix
- Issue templates (bug report, feature request)
- PR template
- MIT License
