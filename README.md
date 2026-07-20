# Agent OS

[![CI](https://github.com/X-code-sourse/agent-os/actions/workflows/ci.yml/badge.svg)](https://github.com/X-code-sourse/agent-os/actions/workflows/ci.yml)

**You write YAML. Agent OS runs AI agents.**

Agent OS is an AI runtime: define a multi-step workflow in a YAML file — search the web, analyze with an LLM, review results, generate a report — and run it with one CLI command. No framework lock-in, no boilerplate.

---

## Install

```bash
cd reference/
pip install -e .
```

Requires Python 3.11+.

## Run

```bash
agentos run stock_research --query "research Nvidia stock for investment"
```

That's it. You'll see a Markdown research report printed to stdout — a 5-step pipeline (search news → search financials → LLM analysis → quality review → final report) executed end-to-end.

### What you get

```text
Available workflows (3):
  competitor_analysis        C:\...\examples\workflows\competitor_analysis.yaml
  finance-stock-research     C:\...\examples\workflows\finance-stock-research.yaml
  stock_research             C:\...\examples\workflows\stock_research.yaml

$ agentos run stock_research --query "research Nvidia stock for investment"

# 📊 Nvidia 研究报告
...
```

```bash
# Save to file
agentos run stock_research --query "research Nvidia" --output report.md

# Machine-readable JSON
agentos run stock_research --query "research Nvidia" --json

# Watch every event as it fires (stderr)
agentos run stock_research --query "research Nvidia" --verbose 2>trace.log
```

---

## How It Works

You write a **workflow** — a YAML file that describes a sequence of tasks and their dependencies. Each task calls a **capability** (search, LLM, review, report…). Capabilities are shared across all workflows; you write the *what*, not the *how*.

```yaml
# examples/workflows/stock_research.yaml
id: stock_research
tasks:
  - id: search_news
    type: search
    params:
      query: "{query} latest news 2025"
    depends_on: []

  - id: search_financials
    type: search
    params:
      query: "{query} financial data revenue"
    depends_on: []

  - id: llm_analysis
    type: llm
    params:
      prompt: |
        Analyze {query} using:
        News:      {search_news.output}
        Financials: {search_financials.output}
        1) Investment highlights
        2) Risk factors
        3) Overall assessment
    depends_on: [search_news, search_financials]

  - id: review_result
    type: review
    params:
      checks: [non_empty, min_length]
    depends_on: [llm_analysis]

  - id: generate_report
    type: report
    params:
      sections:
        - title: "📊 {query} Research Report"
          content: "{llm_analysis.output}"
    depends_on: [review_result]
```

The runtime handles planning (resolves the DAG, prunes unnecessary stages), execution (dispatches tasks to the right capabilities), review (validates quality gates), and reporting — you just write YAML and run it.

---

## CLI Reference

| Command | What it does |
|---------|-------------|
| `agentos run <workflow_id> --query "…"` | Execute a workflow |
| `agentos list` | List available workflows |
| `agentos inspect <workflow_id>` | Show workflow definition |
| `agentos workflow validate <file.yaml>` | Validate a workflow YAML |
| `agentos workflow plan <id> --query "…"` | Show the compiled plan without executing |
| `agentos capability scaffold <name>` | Generate a new capability skeleton |
| `agentos capability discover <path>` | Discover external capabilities |
| `agentos capability validate <path>` | Validate a capability manifest + handler |
| `agentos capability list` | List registered capabilities |

### Validate a Workflow

```bash
agentos workflow validate examples/workflows/stock_research.yaml
```

Shows stage count, dependency graph health, and any validation errors.

### Inspect a Plan (Dry Run)

```bash
agentos workflow plan stock_research --query "research Nvidia stock"
```

Shows which stages survive pruning, which capabilities are bound, and estimated cost/latency.

### Create a Custom Capability

```bash
agentos capability scaffold my-research --output ./capabilities/
```

Generates `manifest.yaml` + `capability.py` — immediately registerable and runnable.

---

## Project Status

**Milestone 0 — Foundation Specification** (complete)

The Agent OS specification is in active development under a spec-driven process. `reference/` contains the P1 runtime implementation.

See [STATUS.md](STATUS.md) for the full project status, RFC table, and promotion pipeline.

---

## Repository Structure

```
agent-os/
├── docs/             — All specification documents
│   ├── vision/       — VISION, PHILOSOPHY, CONSTITUTION
│   ├── spec/         — Core specifications
│   ├── rfc/          — Protocol & module proposals
│   ├── adr/          — Architecture Decision Records
│   └── glossary/     — TERMS.md
├── schemas/          — JSON Schema definitions
├── examples/         — Workflows, rules, capabilities
│   └── workflows/    — stock_research.yaml, competitor_analysis.yaml
├── reference/        — P1 reference implementation (Python)
│   └── src/agentos/  — CLI, engine, registry, planner, SDK
├── tools/            — Doc generators, schema validators
└── .github/          — CI, issue templates
```

---

## Documentation

| Layer | Document | Description |
|-------|----------|-------------|
| Vision | [VISION.md](docs/vision/VISION.md) | Why Agent OS exists |
| Philosophy | [PHILOSOPHY.md](docs/vision/PHILOSOPHY.md) | What we believe |
| Constitution | [CONSTITUTION.md](docs/vision/CONSTITUTION.md) | Principles never to violate |
| Specs | [SPEC-INDEX.md](docs/spec/SPEC-INDEX.md) | Core specifications |
| RFCs | [RFC-INDEX.md](docs/rfc/RFC-INDEX.md) | All proposals |
| ADRs | [ADR-INDEX.md](docs/adr/ADR-INDEX.md) | Architecture decisions |
| Glossary | [docs/glossary/TERMS.md](docs/glossary/TERMS.md) | Term lookup |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture diagram |

---

## Contributing

Agent OS is in its specification phase. Contributions are welcome via Issues.

- **Bug reports**: Found an error in a specification? Open an issue.
- **Feature requests**: Have an idea for a new capability or workflow? Open an issue.
- **PRs**: Not yet open — the core specification must stabilize first.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

[Apache 2.0](LICENSE)
