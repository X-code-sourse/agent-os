# Agent OS

**An AI-native operating platform specification and reference runtime for building composable, governed, and observable AI systems.**

Agent OS is not an AI. It is the operating system that manages all AIs — a platform where Workflows define method, Tasks define intent, Rules embody domain knowledge, Capabilities provide reusable power, and the Kernel orchestrates everything.

```
                    Agent OS
┌─────────────────────────────────────────────────────────┐
│  User Plane       ──  Goals (declarative, no process)   │
│  ───── Event Backbone ─────                             │
│  Control Plane    ──  Kernel (stateless, sole scheduler)│
│  Metadata Plane   ──  Registry (versioned, discoverable)│
│  ───── Event Backbone ─────                             │
│  Data Plane       ──  State (persistent, replayable)    │
│  Runtime Plane    ──  Execution (capabilities, review)  │
└─────────────────────────────────────────────────────────┘
```

## Project Status

**Milestone 0 — Foundation Specification** (in progress)

The project is currently in specification-driven development. No runtime code yet.

## Documentation

| Layer | Document | Description |
|-------|----------|-------------|
| Vision | [VISION.md](docs/vision/VISION.md) | Why Agent OS exists |
| Philosophy | [PHILOSOPHY.md](docs/vision/PHILOSOPHY.md) | What we believe |
| Constitution | [CONSTITUTION.md](docs/vision/CONSTITUTION.md) | Principles never to violate |
| Specs | [SPEC-INDEX.md](docs/spec/SPEC-INDEX.md) | Core specifications |
| RFCs | [RFC-INDEX.md](docs/rfc/RFC-INDEX.md) | Protocol & module proposals |
| ADRs | [ADR-INDEX.md](docs/adr/ADR-INDEX.md) | Architecture decisions |
| Glossary | [docs/glossary/TERMS.md](docs/glossary/TERMS.md) | Quick term lookup |

## Repository Structure

```
agent-os/
├── docs/          — All specification documents
├── schemas/       — JSON Schema / YAML Schema definitions
├── examples/      — Reference examples for all object types
├── reference/     — Future reference implementation
├── tools/         — Documentation generators, schema validators
└── .github/       — CI, templates, issue forms
```

## License

[Apache 2.0](LICENSE)
