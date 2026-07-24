# Changelog

All notable changes to Intent OS are documented here.

---

## v0.12.0 (2026-07-24)

### Environment + Relationship Context — SPEC-0010 Complete

- **`core/environment_context.py`** — New module: `detect_environment()` auto-detects available adapters (by env var + Ollama ping), platform, Python version, and pricing overrides. Pure runtime self-check, no database needed.
- **`core/relationship_context.py`** — New module: `compute_relationships(agent_id)` aggregates team membership and cross-agent collaboration from existing execution_records sharing the same context_id.
- **`intent-os doctor` Environment block** — Doctor output now shows runtime version, platform, adapters status, and default adapter.
- **Injector includes environment + relationships** — `build_injection_prompt()` now injects environment info (runtime, adapters) and relationship info (teams, collaborators) into the LLM system prompt.
- **Context retrieval covers all 6 layers** — `retrieve_context()` now searches identity, capability, experience, environment, and relationship context.
- **16 new tests** — Environment detection, format output, relationship aggregation, empty profiles. 895 tests total, zero regressions.
- **SPEC-0010: Complete** — All six layers of Agent Context now have reference implementations.

---

## v0.11.0 (2026-07-24)

### Context Retrieval — Relevant Context, Not Everything

- **`core/context_retrieval.py`** — New module: `retrieve_context(agent_id, query)` finds the most relevant Capability + Experience entries using keyword matching. No vector DB needed — just structured field matching with a scoring formula that factors in confidence and sample count.
- **Injector now uses retrieval** — `build_injection_prompt()` accepts a `query` parameter. When provided, only context relevant to the user's request is injected. When absent, falls back to loading recent experiences. Saves ~100-300 tokens per call by skipping irrelevant experiences.
- **Proxy extracts user queries** — The proxy automatically extracts the user's latest message from the LLM request body and passes it to the context injector. OpenAI and Anthropic formats both supported.
- **`intent-os context search <agent_id> <query>`** — New CLI command for ad-hoc context retrieval. Shows scored results with source (capability/experience), relevance, and confidence.
- **13 new tests** — Keyword extraction, exact/partial/no-match retrieval, capability matching, empty query fallback, max results limiting, and format output. 879 tests total, zero regressions.

---

## v0.10.0 (2026-07-24)

### Capability Context — Skills with Evidence (SPEC-0010 Layer 2)

- **`core/capability_context.py`** — New module: `compute_capability_profile(agent_id)` aggregates execution records into structured capability profiles with proven success rates, sample counts, cost/token metrics, and preferred models. Not tags — evidence-backed capability proof.
- **`agent get` Capability Context block** — The person-card output now shows each capability with level (expert/proficient/practitioner), success rate, task count, and proven patterns.
- **`context_injector` capability injection** — The proxy now injects "Proven capabilities" into the LLM system prompt: "Financial Analysis: 92% success (3200 tasks, expert)".
- **Experience structured fields** — `structured_situation`, `structured_mistake`, `structured_lesson`, `structured_trigger` added to Experience model. Auto-populated by Failure Pattern extractor. Migration included for existing databases.
- **SPEC-0010 data model validated** — Identity, Capability, and Experience layers now all have working implementations. Working Context and Environment Context ready for future phases.
- **16 new tests** — Capability profile aggregation, cost/token math, level classification, agent isolation. 866 tests total, zero regressions.

---

## v0.9.0 (2026-07-24)

### MCP Agent Resources — Agents Discoverable by Any Runtime

- **MCP resources/list** — The MCP server now exposes all registered agents as URI-addressable resources (`intent-os://agents/{id}`, `/identity`, `/experiences`). Any MCP-compatible client (Claude Code, Cursor) can discover available agents via the standard MCP resource protocol.
- **MCP resources/read** — Clients can read an agent's full `.agent` package, identity profile, or recent experiences through resource URIs. Enables Runtime-native agent loading without proxy interception.
- **`intent-os mcp-server start --agent <id>`** — New `--agent` flag to associate an agent with the MCP server. The agent's identity and capabilities are immediately discoverable.
- **8 MCP resource tests** — Protocol compliance tests for resources/list and resources/read including error cases. 850 tests total, zero regressions.

---

## v0.8.0 (2026-07-24)

### Runtime Self-Awareness — Agent Knows Who It Is

- **Proxy now injects agent identity into LLM requests** — When `intent-os proxy start --agent <id>` is used, the proxy automatically injects a system prompt containing the agent's persona, traits, and recent experiences into every LLM API call. The agent now knows who it is and what it has learned.
- **`core/context_injector.py`** — New module: `build_injection_prompt()` queries AgentStore, ExperienceStore, and ContextStore to build a ~100–250 token system prompt. Handles OpenAI (system role in messages array) and Anthropic (top-level system field) formats.
- **Auto-experience-extraction** — Proxy automatically runs `ExperienceExtractor.extract_all()` every 50 LLM calls. Agent experiences grow without manual `intent-os experience extract`.
- **Doctor feedback loop** — `intent-os doctor` now shows a "Was this diagnosis helpful?" hint with the exact CLI command to record feedback.
- **7 new tests** — Context injector test suite covering identity, experiences, empty traits, cap limits, and OpenAI message formatting. 849 tests total, zero regressions.

---

## v0.7.0 (2026-07-24)

### Agent Package (.agent) — Portable Agent Asset

- **`intent-os agent export <id>`** — Export an agent to a portable `.agent` JSON file containing identity, reputation summary, and experiences. Single file, human-readable, runtime-agnostic.
- **`intent-os agent import <path.agent>`** — Import an agent from a `.agent` file into any Intent OS instance. Generates a new agent_id to avoid conflicts.
- **`core/agent_package.py`** — New module defining the `.agent` format (spec_version 1.0, format `intent-os-agent-v1`), plus `export_agent()`, `import_agent()`, `export_agent_to_file()`, `import_agent_from_file()`.
- **SPEC-0009 upgraded to Frozen v1.0** — Added complete `.agent` JSON schema, field descriptions, export/import behaviour spec, and lifecycle documentation.
- **8 new tests** — Export roundtrip, empty experiences, empty reputation, name override, invalid format rejection, experience preservation. All 842 tests passing.
- **Privacy by design** — `.agent` packages contain only identity + reputation summary. No raw execution data, no API keys, no prompts.

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
