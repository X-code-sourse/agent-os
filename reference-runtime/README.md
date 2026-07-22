# Intent OS

> **An open interoperability layer for AI capabilities, workflows, and execution.**

[![Docs](https://img.shields.io/badge/docs-intent--os.org-blue?style=flat)](https://intent-os.org)
[![Tests](https://img.shields.io/badge/tests-689%20passing-brightgreen?style=flat)]()
[![Version](https://img.shields.io/badge/version-0.4.0-blue?style=flat)]()

Intent OS defines a common model for describing, composing, and executing AI capabilities across different runtimes. It is not a model, not a framework, not a platform — it is an **interoperability layer** that lets AI capabilities move freely between OpenAI, Anthropic, Ollama, OpenRouter, and any future runtime. One manifest, one workflow definition, any runtime.

```bash
pip install "intent-os[all]"
```

**[📖 Documentation →](https://intent-os.org)**

---

## 30-Second Demo

```bash
# Install
pip install intent-os

# Validate a Capability Manifest
intent-os validate examples/translate.yaml

# Execute a capability by name (inline parameters)
intent-os run translate "Hello world" -p target_lang=zh

# Run on any adapter — only the --adapter flag changes
intent-os run translate --adapter openai "Hello world" -p target_lang=zh

# Compare execution across all available runtimes
intent-os compare examples/translate.yaml --input '{"text":"Hello","target_lang":"fr"}'

# Natural language (requires Ollama or API key)
intent-os ask "translate 'good morning' to Japanese"
```

No API key required when using the Ollama adapter (local inference). The same `.yaml` file runs on OpenAI, Anthropic, or any other adapter — only the `--adapter` flag changes.

---

## The Five Problems

| # | Problem | Manifestation | Intent OS Solution |
|---|---|---|---|
| 1 | **Capability Fragmentation** | Same capability rewritten N times for N platforms (Anthropic Tool Use, OpenAI Function Calling, Ollama API, ...) | **Capability Manifest** -- unified description language shaped by SPEC-0001 |
| 2 | **Workflow Lock-in** | Orchestration logic (retry, failure propagation, compensation, parallel execution) tied to one runtime, cannot migrate | **Workflow Graph Spec** -- structure and execution semantics standardised by SPEC-0002 |
| 3 | **Runtime Lock-in** | Users bound to a specific AI platform; switching means rewriting all integrations | **Common Execution Model** via the Adapter layer -- one reference runtime drives OpenAI, Anthropic, Ollama, OpenRouter, GitHub Models |
| 4 | **Engineering Gap** | AI agents lack logs, trace, audit, or cost tracking -- debugging is guesswork | **Event System** -- unified execution record layer (SPEC-0003) with SQLite-backed Event Store and analytics engine |
| 5 | **Ecosystem Void** | No "npm for AI capabilities" -- capabilities are siloed inside platforms | **Capability Registry** with version management, semantic search, import/export tooling, and a future Marketplace (Phase 2+) |

---

## Architecture

```
            AI Applications
                  |
          Workflow Orchestration
                  |
    +------------------------------------------+
    |          Intent OS Common Model           |
    |  +------------+ +----------+ +---------+  |
    |  | Capability | | Workflow | |  Event  |  |
    |  |  Manifest  | |  Graph   | | Schema  |  |
    |  | SPEC-0001  | |SPEC-0002 | |SPEC-0003|  |
    |  +------------+ +----------+ +---------+  |
    |  + Execution Engine + Registry + Security  |
    +------------------------------------------+
                  |
         Runtime Adapter Layer
    +--------+----------+-------+--------------+
    |OpenAI  |Anthropic |Ollama |  OpenRouter  |
    |Adapter |Adapter   |Adapter| Adapter      |
    +--------+----------+-------+--------------+
    | GitHub Models Adapter                      |
    +-------------------------------------------+
                  |
            Models + Tools
```

### Five-Plane Internal Architecture

```
User Plane      Goal / intent from natural language
Control Plane   Planner, Executor, Security Manager -- OWNS NO STATE
Metadata Plane  Registries, policies, versions
Data Plane      Event Store, execution history
Runtime Plane   Model pools, tool pools, adapters
```

All planes communicate through an append-only **Event Bus** which is the single source of truth (CONSTITUTION R3).

---

## CLI Reference

| Command | Description |
|---|---|
| `validate` | Validate a Capability Manifest YAML file against SPEC-0001 |
| `run` | Execute a capability on a runtime adapter (openai, anthropic, ollama, openrouter, github-models) |
| `compare` | Execute the same capability on all loaded adapters and compare execution records |
| `list` | List available adapters and registered capabilities |
| `registry` | Manage the capability registry: list, get, register, unregister, export, search |
| `event` | Query execution events from the Event Store: list, trace, query |
| `analytics` | Analyze execution history: summary, capabilities, runtimes, failures, trends, suggestions, export |
| `workflow` | Plan a workflow from a natural-language goal or run a predefined Workflow Graph (DAG) |
| `mcp-server` | Start an MCP Server (SSE transport) exposing Intent OS capabilities |
| `import` | Import capabilities from external formats: openai-function, mcp-server |
| `export` | Export capabilities to external formats: openai, mcp |
| `quickstart` | Display a step-by-step getting-started guide |
| `evolution` | Run the Evolution Loop for data-driven optimization: run, status, queue, approve, reject |
| `security` | Manage security policies and evaluation: policy list/get/apply, evaluate, audit |

---

## Relationship with MCP

Intent OS and the Model Context Protocol (MCP) are **complementary**, not competitive.

| Dimension | MCP | Intent OS |
|---|---|---|
| Problem solved | AI-to-Tool connection protocol | Capability-to-Capability / Workflow interoperability |
| Standardises | Tool interface | Capability + Workflow + Execution + Event |
| Scope | Transport layer | Execution layer |
| Lifecycle | One-shot tool invocation | Retry, timeout, failure propagation, compensation, parallel execution |

Intent OS can consume MCP servers as Capability Providers (via `import mcp-server`). MCP handles tool discovery and invocation; Intent OS handles capability composition, workflow orchestration, execution semantics, and event recording.

---

## Repository Structure

```
intent-os/
+-- README.md                       # This file
+-- POSITIONING.md                  # Strategic positioning (frozen)
+-- CONSTITUTION.md                 # Core principles and hard constraints (frozen)
+-- ROADMAP.md                      # Evolution roadmap (Phase 0 to Phase 4)
+-- GUIDE.md                        # Full developer guide (zh)
+-- LICENSE                         # AGPLv3
+-- CLAUDE.md                       # AI-assisted development context
|
+-- specs/
|   +-- SPEC-0001-capability-manifest.md    # Capability description format (frozen)
|   +-- SPEC-0002-workflow-graph.md         # Workflow structure + execution semantics (frozen)
|   +-- SPEC-0003-event-schema.md           # Execution event format (frozen)
|   +-- SPEC-0004-security-model.md         # Security model design (Phase 2)
|
+-- schemas/
|   +-- SPEC-0001-capability-manifest.json  # JSON Schema for capability manifests
|   +-- SPEC-0002-workflow-graph.json       # JSON Schema for workflow graphs
|   +-- SPEC-0003-event-schema.json         # JSON Schema for execution events
|
+-- docs/
|   +-- QUICKSTART.md               # 5-minute quickstart guide
|
+-- examples/
|   +-- hello-world/
|   |   +-- hello_world.yaml        # Minimal hello-world capability
|   |   +-- README.md               # Field-by-field walkthrough
|   +-- code_review.yaml            # Code review capability
|   +-- data_extract.yaml           # Data extraction capability
|   +-- image_analyze.yaml          # Image analysis capability
|   +-- sentiment_analyze.yaml      # Sentiment analysis capability
|   +-- translate.yaml              # Translation capability
|
+-- reference-runtime/
|   +-- cli.py                      # CLI entry point (16 commands, 191 lines)
|   +-- mcp_server.py               # MCP Server implementation (SSE transport)
|   +-- setup.py / pyproject.toml   # Package configuration
|   |
|   +-- commands/                   # CLI command implementations (17 files)
|   |   +-- helpers.py              # Shared utilities
|   |   +-- validate.py / run.py / compare.py / list.py
|   |   +-- registry.py / event.py / analytics.py
|   |   +-- workflow.py / mcp_server.py
|   |   +-- import_cmd.py / export.py
|   |   +-- quickstart.py / evolution.py / security.py
|   |
|   +-- core/                       # Core engine (18 modules)
|   |   +-- models.py               # Data models (Manifest, Event, ExecutionRecord)
|   |   +-- parser.py               # Capability Manifest parser
|   |   +-- registry.py             # Capability registry (persistent SQLite)
|   |   +-- executor.py             # Execution engine
|   |   +-- recorder.py             # Event recorder
|   |   +-- event_store.py          # SQLite-backed event store
|   |   +-- analytics.py            # Execution analytics engine
|   |   +-- workflow.py             # Workflow DAG + execution semantics model
|   |   +-- workflow_parser.py      # Workflow YAML parser
|   |   +-- workflow_runner.py      # Workflow executor
|   |   +-- scheduler.py            # Workflow task scheduler
|   |   +-- planner.py              # Goal-based workflow planner
|   |   +-- evolution.py            # Evolution Loop engine
|   |   +-- conditions.py           # Conditional branching DSL
|   |   +-- security.py             # Policy engine and security manager
|   |   +-- search.py               # TF-IDF semantic search engine
|   |
|   +-- adapters/                   # Runtime adapters (5 + base)
|   |   +-- base.py                 # Abstract adapter interface (AdapterBase)
|   |   +-- openai_adapter.py       # OpenAI Function Calling adapter
|   |   +-- anthropic_adapter.py    # Anthropic Tool Use adapter
|   |   +-- ollama_adapter.py       # Ollama native /api/chat adapter
|   |   +-- openrouter_adapter.py   # OpenRouter unified API adapter
|   |   +-- github_models_adapter.py# GitHub Models (OpenAI-compatible) adapter
|   |
|   +-- tools/                      # Import/export tooling
|   |   +-- importer.py             # Import from external formats
|   |   +-- exporter.py             # Export to external formats
|   |   +-- formats/
|   |       +-- openai.py           # OpenAI <-> Manifest conversion
|   |       +-- mcp.py              # MCP <-> Manifest conversion
|   |
|   +-- examples/                   # Example manifests and execution records
|   |   +-- text_summarize.yaml     # Summarization capability
|   |   +-- research_workflow.yaml  # 4-step company research workflow
|   |   +-- anthropic_record.json   # Sample execution record
|   |   +-- openai_record.json
|   |   +-- ollama_record.json
|   |   +-- openrouter_record.json
|   |   +-- github-models_record.json
|   |
|   +-- tests/                      # 17 test files, 560 tests
|       +-- test_adapters.py               (45)  # Adapter schema translation
|       +-- test_cli_commands.py           (37)  # All 16 CLI commands
|       +-- test_executor.py               (41)  # Execution engine
|       +-- test_event_store.py            (35)  # SQLite event store
|       +-- test_import_export.py          (26)  # Format conversion round-trips
|       +-- test_mcp_server.py             (21)  # MCP server protocol
|       +-- test_registry_persistence.py   (29)  # Registry + search
|       +-- test_search.py                 (27)  # TF-IDF search engine
|       +-- test_workflow.py               (39)  # DAG + planner + scheduler
|       +-- test_workflow_integration.py   (28)  # End-to-end workflow execution
|       +-- test_workflow_parser.py        (23)  # Workflow YAML parsing
|       +-- test_conditions.py             (25)  # Condition expression DSL
|       +-- test_adaptive_workflow.py      (11)  # Conditional edges + skip_if
|       +-- test_workflow_adapter_integration.py (3) # Adapter <-> workflow
|       +-- test_evolution.py              (14)  # Evolution Loop
|       +-- test_security.py               (120) # Security Manager
|       +-- test_cross_runtime.py          (42)  # L1-L4 compatibility
|
+-- tests/                          # Top-level compatibility tests (future)
```

---

## Status

**Version:** v0.4.0 — Phase 2: AI Execution Graph

The reference runtime implements:

- **SPEC-0001** Capability Manifest -- parsing, JSON Schema validation, and execution
- **SPEC-0002** Workflow Graph -- DAG-based workflow composition with configurable execution semantics (retry, timeout, failure propagation, parallel execution, compensation)
- **SPEC-0003** Event Schema -- structured execution recording, SQLite-backed Event Store, and analytics engine
- **SPEC-0004** Security Model -- policy engine with risk evaluation, layered permissions, and compliance auditing
- **5 Runtime Adapters** -- OpenAI, Anthropic, Ollama (local), OpenRouter, GitHub Models
- **Capability Registry** -- persistent SQLite storage, version management, TF-IDF semantic search
- **Evolution Loop** -- data-driven optimization suggestion engine with approval workflow
- **Import / Export** -- bidirectional conversion between Intent OS manifests and OpenAI function definitions / MCP tool descriptions
- **Adaptive Execution Graph** -- conditional branching DSL (`skip_if`, `conditions`) for runtime workflow adaptation
- **Workflow Planner** -- goal-based template planner that generates DAGs from natural-language goals
- **Cross-Runtime Compatibility Test Suite** -- automated L1-L4 verification (schema, capability, semantic contract, execution record)
- **560 Tests** -- 552 passing, 8 skipped (require Ollama), covering every component

### 560-Test Map

| Test file | Tests | Area |
|---|---|---|
| `test_security.py` | 120 | Security policy evaluation |
| `test_adapters.py` | 45 | Adapter schema translation + cost |
| `test_executor.py` | 41 | Execution engine |
| `test_cross_runtime.py` | 42 | L1-L4 compatibility |
| `test_workflow.py` | 39 | DAG + planner + scheduler |
| `test_event_store.py` | 35 | SQLite event store |
| `test_cli_commands.py` | 37 | All 16 CLI commands |
| `test_registry_persistence.py` | 29 | Registry + search |
| `test_workflow_integration.py` | 28 | End-to-end workflows |
| `test_search.py` | 27 | TF-IDF search |
| `test_import_export.py` | 26 | Format round-trips |
| `test_conditions.py` | 25 | Condition DSL |
| `test_workflow_parser.py` | 23 | YAML parsing |
| `test_mcp_server.py` | 21 | MCP protocol |
| `test_evolution.py` | 14 | Evolution Loop |
| `test_adaptive_workflow.py` | 11 | Conditional edges |
| `test_workflow_adapter_integration.py` | 3 | Adapter <-> workflow |
| **Total** | **560** | |

---

## License

Copyright (C) 2026 Intent OS Project

Licensed under the GNU Affero General Public License v3.0 (AGPLv3).
