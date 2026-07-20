# Quickstart — Agent OS

**Prerequisites:** Python 3.11+, pip

## Install

```bash
cd reference
pip install -e .
```

## Your First Run

```bash
agentos run stock_research --query "research Nvidia stock for investment"
```

You'll see a Markdown report showing a 5-task pipeline execute: search news → search financials → LLM analysis → quality review → final report.

```bash
# Save report to file
agentos run stock_research --query "research Nvidia stock" --output report.md

# Machine-readable JSON
agentos run stock_research --query "research Nvidia stock" --json

# Watch Event trace (stderr)
agentos run stock_research --query "research Nvidia stock" --verbose 2>trace.log
```

## Validate a Workflow

```bash
agentos workflow validate reference/workflows/stock_research.yaml
```

Shows stage count, dependency graph health, and any validation errors with error codes (SPEC-0000 §11).

## Inspect a Plan (Without Executing)

```bash
agentos workflow plan stock_research --query "research Nvidia stock"
```

Shows: which stages survive pruning, which Capabilities are bound, estimated cost and latency.

## Create a Custom Capability

```bash
agentos capability scaffold my-research --output ./capabilities/
```

Generates `manifest.yaml` + `capability.py` — immediately registerable and invocable.

## What's Next

| Resource | Description |
|----------|-------------|
| [VISION.md](docs/vision/VISION.md) | Why Agent OS exists |
| [CONSTITUTION.md](docs/vision/CONSTITUTION.md) | 15 architectural principles |
| [RFC-INDEX.md](docs/rfc/RFC-INDEX.md) | All 16 RFCs |
| [RFC-0700](docs/rfc/RFC-0700-cli-quickstart.md) | CLI specification (this interface) |
| [reference/](reference/) | Reference implementation |
| [examples/workflows/](examples/workflows/) | Example workflow YAML files |
