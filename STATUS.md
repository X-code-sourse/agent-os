# STATUS — Agent OS Project Status

**Last updated:** 2026-07-19
**Milestone:** 0 — Foundation Specification

---

## Milestone 0: Foundation Specification

**Goal:** Establish the complete Agent OS specification — language, object model, architectural constitution, and all core module RFCs — so that any implementation can begin from a stable, internally consistent set of documents.

### Deliverables

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 1 | VISION.md | ✅ Accepted | Stable |
| 2 | PHILOSOPHY.md | ✅ Accepted | Stable |
| 3 | CONSTITUTION.md | ✅ Accepted | 15 Articles, 4 Layers — stable |
| 4 | SPEC-0000 Core Concepts | ⬆ **Proposed** | See SPEC-0000 entry below |
| 5 | SPEC-INDEX | ✅ Done | Single entry (SPEC-0000) |
| 6 | RFC-INDEX | ✅ Done | 15 RFC entries, 22 slots total |
| 7 | ADR-INDEX + 2 ADRs | ✅ Done | ADR-0001 (Event Sourcing), ADR-0002 (Kernel Stateless) |
| 8 | Repository structure | ✅ Done | All directories populated with .gitkeep |
| 9 | Glossary (TERMS.md) | ✅ Done | 40+ terms |
| 10 | Examples | ✅ Done | 1 Workflow, 1 Rule |

**Milestone 0 completion criteria:** SPEC-0000 and RFC-0001 promoted to Proposed. (Current: SPEC-0000 promoted, RFC-0001 still Draft.)

---

## RFC Status Table

| ID | Title | Plane | Status | Referenced By | Promotion Criteria |
|----|-------|-------|--------|---------------|--------------------|
| SPEC-0000 | Core Concepts & Object Model | — | **Proposed** | All 14 RFCs, 2 ADRs | ✅ Complete — all S1 issues resolved |
| RFC-0001 | Execution Semantics | Foundation | Draft | RFC-0101, RFC-0102, RFC-0200, RFC-0500, RFC-0600 | ⏳ Awaiting promotion |
| RFC-0002 | Constitutional Reference | Foundation | Draft | (Reference wrapper) | ✅ Wrapper — promotes with RFC-0001 |
| RFC-0100 | Workflow Specification | Control | Draft | RFC-0101, RFC-0102, RFC-0201 | ⏳ Awaiting implementation validation |
| RFC-0101 | Planner Architecture | Control | **Proposed** | RFC-0102 | ⏳ Awaiting implementation validation |
| RFC-0102 | Execution Engine | Control | Draft | RFC-0200, RFC-0501 | ⏳ Awaiting implementation validation |
| RFC-0104 | Rule Resolution | Control | Draft | RFC-0600 | ⏳ Awaiting implementation validation |
| RFC-0200 | Capability Contract | Runtime | Draft | RFC-0201, RFC-0202, RFC-0203 | ⏳ Awaiting implementation validation |
| RFC-0201 | Capability Manifest | Runtime | Draft | RFC-0202, RFC-0300 | ⏳ Awaiting implementation validation |
| RFC-0202 | Capability Negotiation | Runtime | Draft | RFC-0300 | ⏳ Awaiting implementation validation |
| RFC-0203 | Runtime Scheduling | Runtime | Draft | (none yet) | ⏳ No blockers |
| RFC-0300 | Registry | Metadata | Draft | RFC-0600 | ⏳ Awaiting implementation validation |
| RFC-0500 | Event Backbone | Infrastructure | Draft | RFC-0501, RFC-0502 | ⏳ Awaiting implementation validation |
| RFC-0501 | Observability | Infrastructure | Draft | RFC-0600 | ⏳ Awaiting implementation validation |
| RFC-0502 | Security | Infrastructure | Draft | Constitution A13–A15 | ⏳ No blockers |
| RFC-0600 | Loop Learning | Evolution | Draft | (none yet) | ⏳ Awaiting implementation validation |

---

## RFC Dependency Graph

```
                        SPEC-0000 (根 — 被全部引用)
                           │
              ┌────────────┼────────────┬──────────────┐
              ▼            ▼            ▼              ▼
         RFC-0001     RFC-0100     RFC-0200        RFC-0500
         (foundation) (workflow)   (contract)      (backbone)
              │            │            │              │
              ▼            ▼            ▼              ▼
         RFC-0101     RFC-0101     RFC-0201        RFC-0501
         (planner)    (planner)    (manifest)      (observability)
              │            │            │              │
              ▼            ▼            ▼              ▼
         RFC-0102     RFC-0102     RFC-0202        RFC-0600
         (engine)     (engine)     (negotiation)   (loop)
              │                         │
              ▼                         ▼
         RFC-0200                  RFC-0300
         (contract)                (registry)
              │                         │
              ▼                         ▼
         RFC-0203                  RFC-0600
         (scheduling)              (loop)

         RFC-0104 (rule) ──► RFC-0600 (loop)
         RFC-0502 (security) ──► Constitution (standalone)
```

---

## Promotion Pipeline

### Currently Proposed (1)

| RFC | Reason for Proposed Status | Next Step |
|-----|---------------------------|-----------|
| SPEC-0000 | Root of all references, all S1 issues resolved | Begin reference implementation |
| RFC-0101 | All referenced by downstream RFCs, no unresolved issues | Await implementation validation |

### Next in Line for Promotion

| RFC | Prerequisite | Condition |
|-----|-------------|-----------|
| RFC-0001 | SPEC-0000 → Proposed | ✅ Dependency met. Phase 1-2 S1 issues resolved. Ready. |
| RFC-0100 | RFC-0001 → Proposed | Awaiting upstream stabilization |
| RFC-0102 | RFC-0100 + RFC-0101 → Proposed | Awaiting upstream stabilization |
| RFC-0200 | RFC-0001 → Proposed | Awaiting upstream stabilization |

---

## RFC Coverage by Plane

| Plane | Total Slots | Written | Coverage |
|-------|-------------|---------|----------|
| Foundation | 2 | 2 | 100% |
| Control | 4 | 4 | 100% |
| Runtime | 4 | 4 | 100% |
| Metadata | 3 | 1 | 33% (RFC-0301/0302 absorbed by 0300) |
| Infrastructure | 3 | 3 | 100% |
| Evolution | 3 | 1 | 33% (RFC-0601/0602 absorbed by 0600/0104) |
| **Total** | **22** | **15** | **68%** (100% of unique RFCs written; 7 slots are absorbed content) |

---

## ADR Status

| ADR | Title | Status |
|-----|-------|--------|
| ADR-0001 | Event Sourcing | ✅ Accepted |
| ADR-0002 | Kernel Stateless | ✅ Accepted |

---

## Known Gaps (Not Blocking Milestone 0)

1. **Phase 4 RFC-0100 gaps** — Loop/Timer stage types, exclusive_gate pruning, failure propagation strategy, conflict resolution DSL
2. **Schema extraction** — No standalone JSON Schema files in `/schemas/` yet
3. **Reference implementation** — `/reference/` directory is empty
4. **Open Questions across RFCs** — ~25 total across all RFCs, none blocking promotion

---

## How to Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md).

- **To review a RFC:** Open an Issue with the RFC ID in the title
- **To propose a new RFC:** Use the RFC template (coming soon)
- **To report a specification bug:** Open an Issue with prefix `[SPEC]` or `[RFC-NNNN]`
- **To start an implementation discussion:** Open a Discussion
