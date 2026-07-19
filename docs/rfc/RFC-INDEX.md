# RFC-INDEX

RFCs (Requests for Comments) define how specific modules and protocols are implemented. They reference SPECs for terminology and object definitions.

## Proposed RFC Tree

### Foundation
| ID | Title | Status |
|----|-------|--------|
| RFC-0001 | Execution Semantics | Draft |
| RFC-0002 | Architectural Constitution (reference only) | Draft |

### Control Plane
| ID | Title | Status |
|----|-------|--------|
| RFC-0100 | Workflow Specification | Draft |
| RFC-0101 | Planner Architecture | Proposed |
| RFC-0102 | Execution Engine | Draft |
| RFC-0103 | State Machine | — |
| RFC-0104 | Rule Resolution | — |

### Runtime
| ID | Title | Status |
|----|-------|--------|
| RFC-0200 | Capability Contract | Draft |
| RFC-0201 | Capability Manifest | Draft |
| RFC-0202 | Capability Negotiation | — |
| RFC-0203 | Runtime Scheduling | — |

### Metadata
| ID | Title | Status |
|----|-------|--------|
| RFC-0300 | Registry | — |
| RFC-0301 | Versioning | — |
| RFC-0302 | Discovery Protocol | — |

### Data
| ID | Title | Status |
|----|-------|--------|
| RFC-0400 | Memory Architecture | — |
| RFC-0401 | Knowledge Store | — |
| RFC-0402 | Event Store | — |
| RFC-0403 | Execution Record | — |

### Infrastructure
| ID | Title | Status |
|----|-------|--------|
| RFC-0500 | Event Backbone | — |
| RFC-0501 | Observability | — |
| RFC-0502 | Security | — |

### Evolution
| ID | Title | Status |
|----|-------|--------|
| RFC-0600 | Loop Learning | — |
| RFC-0601 | Optimization | — |
| RFC-0602 | Experiment Framework | — |

## Process

1. Author drafts an RFC
2. Submit via PR to `draft` branch
3. Community and maintainers review
4. If accepted, merge to `main`
5. If rejected, close with ADR explaining why
