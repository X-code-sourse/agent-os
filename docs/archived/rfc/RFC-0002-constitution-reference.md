# RFC-0002: Architectural Constitution (Reference)

**Status:** Draft
**Type:** Foundation RFC
**Supersedes:** Nothing
**Depends on:** CONSTITUTION.md
**Author:** Architecture Team
**Date:** 2026-07-19

---

## 1. Purpose

This RFC exists solely to import the [Architectural Constitution](../vision/CONSTITUTION.md) into the RFC reference system. It does not redefine or modify any Article. Subsequent RFCs can reference "RFC-0002" instead of a file path.

---

## 2. Reference

The full text of the Architectural Constitution lives at:

**`docs/vision/CONSTITUTION.md`**

### Layer I: Core Constitution (Inviolable)

| Article | Title |
|---------|-------|
| Article 1 | The Kernel Must Be Stateless |
| Article 2 | The Execution Engine Is the Sole Scheduler |
| Article 3 | All Persistent State Must Live in the Data Plane |
| Article 4 | All Cross-Module Communication Must Go Through the Event Backbone |

### Layer II: Boundary Constitution (Responsibility Isolation)

| Article | Title |
|---------|-------|
| Article 5 | Workflow Describes Flow Only |
| Article 6 | Rule Describes Constraint Only |
| Article 7 | Capability Implements Ability Only |
| Article 8 | Workflow Depends on Capability Requirements, Not Implementations |

### Layer III: Evolution Constitution (Growth Principles)

| Article | Title |
|---------|-------|
| Article 9 | Planner Optimizes at Compile Time Only (v1) |
| Article 10 | Loop Has Suggestion Rights Only |
| Article 11 | The Metadata Registry Is the Only Discovery Entry Point |
| Article 12 | Model Selection Is a Capability Internal Concern |

---

## 3. Usage

Throughout the RFC series, citations of the Constitution follow this form:

> Per Constitution Article 2, the Execution Engine is the sole scheduler.
> (RFC-0002, Article 2)

---

## 4. Amendment

The Constitution has its own amendment process (see CONSTITUTION.md §Amendment Process). This RFC is updated in lockstep with Constitution changes.
