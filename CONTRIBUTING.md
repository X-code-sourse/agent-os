# Contributing to Intent OS

Thank you for your interest in Intent OS! This document covers the basics of getting involved.

## Project overview

Intent OS is an **open-source observability layer for AI agents**. We're building the execution layer that makes agents observable, governable, and portable across runtimes. See [README](README.md) for the full project overview.

## Getting started

```bash
git clone https://github.com/haihaoxu/intentos.git
cd intentos/reference-runtime
pip install -e .

# Run the tests
python -m pytest tests/ -q
```

## How to contribute

### Reporting bugs

Open a [Bug Report](https://github.com/haihaoxu/intentos/issues/new?labels=bug&template=bug_report.md). Include:
- The exact command that triggered the bug
- Your environment (OS, Python version, adapter)
- The full error output

### Suggesting features

Open a [Feature Request](https://github.com/haihaoxu/intentos/issues/new?labels=enhancement&template=feature_request.md). Tell us:
- What problem you're trying to solve
- How you imagine the solution working
- What alternatives you've considered

### Submitting code

1. Fork the repository
2. Create a branch: `git checkout -b feat/your-feature-name`
3. Make your changes
4. Run the tests: `cd reference-runtime && python -m pytest tests/ -q`
5. Submit a Pull Request

## Code conventions

- Python 3.10+ with `from __future__ import annotations`
- `dataclass` for data models, not hand-written classes
- Filenames: `snake_case.py`
- Classes: `PascalCase`, methods/variables: `snake_case`
- CLI commands in `commands/` with lazy imports in function body
- All adapters inherit `adapters/base.py::AdapterBase`
- Module docstring starts with `"Intent OS — "`
- Tests: `class TestComponent`, `def test_scenario`, plain `assert`

## Spec conventions

New Specs follow `specs/SPEC-NNNN-name.md` and include:
- Purpose (what question does it answer)
- Design Principles
- Specification with YAML/JSON examples
- Validation rules (each must be testable)

## Running tests

```bash
# Full suite
cd reference-runtime
python -m pytest tests/ -v --tb=short

# Single test file
python -m pytest tests/test_security.py -v

# Fast check
python -m pytest tests/ --tb=no -q
```

## Project structure

```
intent-os/
├── specs/                    # Specification documents
├── schemas/                  # JSON Schema files
├── examples/                 # Capability Manifest examples
├── reference-runtime/        # Reference implementation
│   ├── core/                 # Engine modules
│   ├── adapters/             # Runtime adapters
│   ├── commands/             # CLI commands
│   ├── tools/                # Import/Export
│   └── tests/                # Test suite (680+ tests)
└── .github/workflows/        # CI configuration
```

## Questions?

Open a [Discussion](https://github.com/haihaoxu/intentos/discussions) or reach out on GitHub Issues.
