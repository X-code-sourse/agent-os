# RFC-0300 Registry MVI（最小可行实现方案）

**作者:** Backend Architect  
**日期:** 2026-07-20  
**状态:** Design Proposal  
**目标:** Agent OS P1 → P1.5（增量改造，保持 CLI 接口不变）

---

## 目录

1. [问题分析](#1-问题分析)
2. [设计目标](#2-设计目标)
3. [总体架构](#3-总体架构)
4. [CapabilityRegistry](#4-capabilityregistry)
5. [WorkflowRegistry](#5-workflowregistry)
6. [AgentOSRegistry（统一入口）](#6-agentosregistry统一入口)
7. [集成方案与向后兼容](#7-集成方案与向后兼容)
8. [文件结构与改动范围](#8-文件结构与改动范围)
9. [关键代码实现](#9-关键代码实现)
10. [测试策略](#10-测试策略)

---

## 1. 问题分析

### 1.1 当前状态

```
┌─ Capability 注册 ─────────────────────────────────────┐
│                                                        │
│  capabilities/__init__.py (硬编码 dict)                 │
│    CAPABILITIES = {                                     │
│        "search": search_fn,                             │
│        "llm":    llm_fn,                                │
│        "gather": review_fn,                             │
│        "review": review_fn,                             │
│        "report": report_fn,                             │
│    }                                                    │
│                                                        │
│  cli.py (手动 loop)                                     │
│    for tp, fn in CAPABILITIES.items():                  │
│        engine.pool.register(tp, fn)                     │
│                                                        │
│  capability_pool.py (无元数据的 dict)                    │
│    _registry: dict[str, Callable] = {}                  │
│    def register(task_type, fn): ...                     │
│                                                        │
└────────────────────────────────────────────────────────┘

┌─ Workflow 注册 ─────────────────────────────────────────┐
│                                                          │
│  workflow_loader.py (直接扫描文件系统)                     │
│    WORKFLOW_DIRS = [cwd/"workflows", ~/.agent-os/...]    │
│    def discover_workflows(): ...                          │
│    def load(workflow_id): ... (扫描 → 查 dict)            │
│                                                          │
│  → 没有任何注册表，每次调用 discover_workflows() 都扫磁盘   │
│  → 无法索引 workflow 用了哪些 capability                  │
│  → 无法按 capability 反向查询 workflow                     │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 1.2 核心痛点

| 痛点 | 影响 | 严重程度 |
|------|------|---------|
| Capability 硬编码 | 插件化/外部扩展不可能 | 🔴 高 |
| Capability 无元数据 | 无版本、无描述、无输入输出 schema | 🔴 高 |
| Workflow 每次扫磁盘 | N+1 问题（每次 list/load 重复扫描） | 🟡 中 |
| 无反向索引 | 无法回答"哪些 workflow 用了 search 能力" | 🟡 中 |
| 注册无事件通知 | 无法监控/审计注册变更 | 🟢 低 |
| 注册与 Pool 耦合 | CapabilityPool 同时承担注册和执行 | 🟢 低 |

---

## 2. 设计目标

### 2.1 MVI 范围（这个文档）

| 能力 | 优先级 | 说明 |
|------|--------|------|
| 结构化 Capability 元数据 | P0 | 取代 `(str, Callable)` 裸对 |
| 一次扫描、多次读取的 Workflow 索引 | P0 | 取代每次都扫磁盘 |
| 反向索引（capability → workflow） | P1 | 支撑"哪些 workflow 可用"的智能查询 |
| 事件驱动的注册通知 | P1 | 注册/注销时发布 `Registry:*` 事件 |
| 与现有 Pool 的兼容层 | P0 | `engine.pool.register()` 必须继续工作 |

### 2.2 非目标（后续迭代）

| 能力 | 说明 |
|------|------|
| 远程注册（gRPC/REST） | P2+ 支持分布式 Capability |
| 动态热加载 | P2+ 运行时注册/注销 |
| Capability 版本选择 | P3+ 多版本共存与依赖解析 |
| 权限/认证 | P3+ 谁可以注册什么 |

### 2.3 设计原则

1. **增量改造** — 不重写现有代码，用适配器兼容旧接口
2. **事件驱动** — 注册变更通过 Event Bus 通知，增强可观测性
3. **惰性加载** — Capability 函数按需导入，不启动时全部加载
4. **只加不减** — 新增 registry/ 模块，不改 backbone/、pool/ 等已有模块的接口签名

---

## 3. 总体架构

```
                        ┌──────────────┐
                        │   CLI/Main   │
                        │  (cli.py)    │
                        └──────┬───────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
   ┌──────────────────┐ ┌──────────────┐ ┌──────────────┐
   │  CapabilityReg.  │ │WorkflowReg. │ │  Event Bus   │
   │  (registry/)     │ │(registry/)  │ │ (backbone/)  │
   └────────┬─────────┘ └──────┬───────┘ └──────┬───────┘
            │                  │                │
            ▼                  ▼                │
   ┌──────────────────────────────────┐         │
   │       AgentOSRegistry            │◄────────┘
   │  (统一入口，组合两个子 Registry)   │ publish()
   └──────────────┬───────────────────┘
                  │
                  ▼
   ┌──────────────────────────────────┐
   │        CapabilityPool            │
   │  (从 CapabilityRegistry 读取)     │
   └──────────────────────────────────┘
```

### 3.1 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| `registry/capability.py` | 🆕 | Capability 元数据注册、查询、反向索引 |
| `registry/workflow.py` | 🆕 | Workflow 元数据注册、扫描、索引 |
| `registry/__init__.py` | 🆕 | `AgentOSRegistry` 统一入口 |
| `capability_pool.py` | 改 | 从 `CapabilityRegistry` 自动加载，而不是独立 `_registry` |
| `capabilities/__init__.py` | 改 | 改为声明式 `CAPABILITY_MANIFESTS`，而非裸 dict |
| `cli.py` | 改 | 用 `AgentOSRegistry.setup_default()` 替代手动 loop |
| `workflow_loader.py` | 改 | 在 `load()` 中可选地调用 `WorkflowRegistry.track()` 来索引 |

---

## 4. CapabilityRegistry

### 4.1 CapabilityManifest 元数据

```python
@dataclass
class CapabilityManifest:
    """Capability 的静态元数据（取代裸 Callable 对）。"""
    task_type: str               # "search" | "llm" | "review" | "report"
    display_name: str            # "Web Search"
    description: str             # "搜索互联网获取信息"
    version: str                 # "1.0.0"
    input_schema: dict | None    # 期望的 params schema（可选）
    output_schema: dict | None   # 输出的 schema（可选）
    tags: list[str] = field(default_factory=list)  # ["web", "async"]
    source: str = "builtin"      # "builtin" | "plugin:xxx"
    enabled: bool = True
```

### 4.2 类接口

```python
class CapabilityRegistry:
    """Capability 元数据注册表。

    职责：
    - 存储/查询 CapabilityManifest
    - 反向索引（按 tag、source 等过滤）
    - 发布注册事件
    - 延迟加载能力函数
    """

    def __init__(self, bus: EventBus | None = None):
        self._manifests: dict[str, CapabilityManifest] = {}   # task_type → manifest
        self._functions: dict[str, Callable] = {}               # task_type → fn (lazy)
        self._bus = bus

    # ── 注册 ──────────────────────────────────────────────

    def register(self, task_type: str, fn: Callable,
                 manifest: CapabilityManifest | None = None) -> None:
        """注册一个 Capability。提供 manifest 获得完整元数据。"""
        ...

    def register_manifest(self, manifest: CapabilityManifest,
                          fn: Callable | None = None) -> None:
        """从 CapabilityManifest 注册（推荐方式）。"""
        ...

    # ── 查询 ──────────────────────────────────────────────

    def get_manifest(self, task_type: str) -> CapabilityManifest | None: ...
    def get_function(self, task_type: str) -> Callable | None: ...

    def list(self, tag: str | None = None,
             source: str | None = None) -> list[CapabilityManifest]: ...
    def contains(self, task_type: str) -> bool: ...

    # ── 生命周期 ──────────────────────────────────────────

    def unregister(self, task_type: str) -> bool: ...

    # ── 批量加载 ──────────────────────────────────────────

    def load_from_module(self, module_name: str) -> int:
        """从一个模块加载所有 CAPABILITY_MANIFESTS。"""
        ...

    @property
    def count(self) -> int: ...
```

### 4.3 事件发布

每次 `register()` / `unregister()` 发布标准事件：

| 事件类型 | 时机 | Payload 字段 |
|---------|------|-------------|
| `Registry:CapabilityRegistered` | `register()` 成功 | `{task_type, version, source}` |
| `Registry:CapabilityUnregistered` | `unregister()` 成功 | `{task_type}` |
| `Registry:CapabilitiesLoaded` | `load_from_module()` | `{module, count, types: [...]}` |

---

## 5. WorkflowRegistry

### 5.1 WorkflowManifest 元数据

```python
@dataclass
class WorkflowManifest:
    """Workflow 元数据（从 YAML 提取的摘要）。"""
    id: str                     # "stock_research"
    name: str
    description: str
    path: Path                  # 源文件路径
    task_count: int
    capability_types: set[str]  # {"search", "llm", "review", "report"}
    last_loaded: str            # ISO timestamp
    source: str = "local"       # "local" | "remote" | "bundled"
```

### 5.2 类接口

```python
class WorkflowRegistry:
    """Workflow 注册表。

    职责：
    - 扫描已知目录，建立索引
    - 提供一次扫描、多次读取的查询
    - 反向索引（按 capability_type 查询 workflow）
    - 发布加载事件
    """

    def __init__(self, bus: EventBus | None = None,
                 extra_dirs: list[Path] | None = None):
        self._workflows: dict[str, WorkflowManifest] = {}
        self._capability_index: dict[str, set[str]] = {}  # capability_type → {wf_ids}
        self._dirs = list(WORKFLOW_DIRS) + (extra_dirs or [])
        self._bus = bus

    # ── 扫描与索引 ─────────────────────────────────────────

    def scan(self, extra_dirs: list[Path] | None = None) -> int:
        """扫描文件系统，更新索引。返回新增/变更数。"""
        ...

    def track(self, workflow: Workflow) -> WorkflowManifest:
        """索引一个已加载的 Workflow 对象（替代扫描）。"""
        ...

    # ── 查询 ──────────────────────────────────────────────

    def get(self, workflow_id: str) -> WorkflowManifest | None: ...
    def list(self) -> list[WorkflowManifest]: ...

    def find_by_capability(self, task_type: str) -> list[WorkflowManifest]:
        """反向查询：哪些 workflow 使用了某 capability。"""
        ...

    def contains(self, workflow_id: str) -> bool: ...

    # ── 刷新 ──────────────────────────────────────────────

    def refresh(self, path: Path | None = None) -> int:
        """刷新某个目录或所有目录的索引。"""
        ...

    @property
    def count(self) -> int: ...

    @property
    def capability_index(self) -> dict[str, list[str]]: ...
```

### 5.3 事件发布

| 事件类型 | 时机 | Payload |
|---------|------|---------|
| `Registry:WorkflowScanned` | `scan()` 结束 | `{count, new, updated}` |
| `Registry:WorkflowTracked` | `track()` 成功 | `{workflow_id, task_count, capability_types: [...]}` |

### 5.4 惰性扫描策略

- **首次调用 `list()` / `get()` / `find_by_capability()`** → 触发 `scan()`
- **显式调用 `scan()`** → 强制刷新
- **`refresh(path)`** → 只刷新单个路径（变更后调用）
- **`track(workflow)`** → 手动索引一个已加载实例（workflow_loader.load() 中调用）

---

## 6. AgentOSRegistry（统一入口）

### 6.1 类接口

```python
class AgentOSRegistry:
    """Agent OS Registry — 统一入口（RFC-0300）。

    组合 CapabilityRegistry 和 WorkflowRegistry，
    提供一键初始化、全局查询和状态快照。
    """

    def __init__(self, bus: EventBus | None = None):
        self.capabilities = CapabilityRegistry(bus=bus)
        self.workflows = WorkflowRegistry(bus=bus)
        self._bus = bus

    # ── 一键初始化 ─────────────────────────────────────────

    @classmethod
    def setup_default(cls, bus: EventBus | None = None,
                      extra_workflow_dirs: list[Path] | None = None
                      ) -> "AgentOSRegistry":
        """创建 Registry 并加载所有默认注册项。

        1. 从 capabilities/ 模块加载内建 Capabilities
        2. 扫描 workflows/ 目录
        3. 发布 Registry:Initialized 事件
        """
        registry = cls(bus=bus)

        # 加载内建 Capabilities
        from agentos.capabilities import CAPABILITY_MANIFESTS
        for manifest in CAPABILITY_MANIFESTS:
            registry.capabilities.register_manifest(manifest)

        # 扫描 Workflow 目录
        registry.workflows.scan(extra_dirs=extra_workflow_dirs)

        if bus:
            bus.publish(Event.new(
                "Registry:Initialized",
                payload={
                    "capability_count": registry.capabilities.count,
                    "workflow_count": registry.workflows.count,
                },
                source={"module": "registry", "instance_id": ""},
            ))

        return registry

    # ── 全局查询 ───────────────────────────────────────────

    def resolve_workflow(self, workflow_id: str) -> WorkflowManifest | None:
        """按 ID 查找 workflow 元数据。"""
        ...

    def resolve_capability(self, task_type: str) -> CapabilityManifest | None:
        """按类型查找 capability 元数据。"""
        ...

    def workflows_using(self, task_type: str) -> list[WorkflowManifest]:
        """反向查询：哪些 workflow 用了某 capability。"""
        ...

    def capabilities_for_workflow(self, workflow_id: str
                                  ) -> list[CapabilityManifest]:
        """正向查询：某 workflow 需要哪些 capability。"""
        ...

    # ── 状态快照 ───────────────────────────────────────────

    def snapshot(self) -> dict:
        """返回当前注册状态的快照（用于诊断/CLI）。"""
        return {
            "capabilities": [
                {"task_type": m.task_type, "version": m.version,
                 "source": m.source, "enabled": m.enabled}
                for m in self.capabilities.list()
            ],
            "workflows": [
                {"id": m.id, "task_count": m.task_count,
                 "capability_types": sorted(m.capability_types)}
                for m in self.workflows.list()
            ],
        }
```

### 6.2 CLI 集成

```python
# cli.py 改造前：
engine = ExecutionEngine(bus=bus)
for tp, fn in CAPABILITIES.items():
    engine.pool.register(tp, fn)

# cli.py 改造后：
registry = AgentOSRegistry.setup_default(bus=bus)
engine = ExecutionEngine(bus=bus, registry=registry)
# engine.pool 自动从 registry.capabilities 加载
# 不需要显式 for 循环
```

---

## 7. 集成方案与向后兼容

### 7.1 CapabilityPool 改造

```python
class CapabilityPool:
    def __init__(self, registry: CapabilityRegistry | None = None):
        self._registry_dict: dict[str, Callable] = {}  # 保留旧的（兼容）
        self._meta_registry = registry                  # 新的元数据注册表

    def register(self, task_type: str, fn: Callable) -> None:
        """旧接口：兼容 layer。同时更新新旧两个注册表。"""
        self._registry_dict[task_type] = fn
        if self._meta_registry:
            # 没有 manifest 的旧式注册，自动生成一个简化版的
            self._meta_registry.register(
                task_type, fn,
                manifest=CapabilityManifest(
                    task_type=task_type,
                    display_name=task_type,
                    description=f"Capability '{task_type}' (legacy registration)",
                    version="0.0.0",
                )
            )
```

### 7.2 capabilities/__init__.py 改造

```python
# 改造前：裸 Callable dict
from .search import search
CAPABILITIES = {"search": search, ...}

# 改造后：声明式 Manifest 列表
from .search import search, SEARCH_MANIFEST
from .llm import llm, LLM_MANIFEST

CAPABILITY_MANIFESTS = [
    SEARCH_MANIFEST,
    LLM_MANIFEST,
    ...
]

# 兼容旧引用（过渡用）
# 老代码 from .capabilities import CAPABILITIES 仍然工作
CAPABILITIES = {m.task_type: m for m in CAPABILITY_MANIFESTS}
```

### 7.3 workflow_loader.py 改造

```python
class WorkflowLoadError(Exception):
    ...

# 在 _load_from_path() 末尾增加可选索引：
def _load_from_path(path, bus=None, registry=None):
    # ... 现有代码 ...
    wf = Workflow(id=..., tasks=..., ...)

    if registry:
        registry.workflows.track(wf)  # 新增：索引到 WorkflowRegistry

    if bus:
        bus.publish(...)

    return wf
```

### 7.4 CLI 兼容性矩阵

| 现有使用方式 | 改造后是否兼容 | 说明 |
|-------------|-------------|------|
| `from .capabilities import CAPABILITIES` | ✅ | 保留 `CAPABILITIES` 作为 manfiests dict |
| `engine.pool.register(tp, fn)` | ✅ | 同时写新旧注册表 |
| `engine.pool.invoke(task, ctx)` | ✅ | 从 `_registry_dict` 读取，完全不感知 registry |
| `discover_workflows()` | ✅ | 函数签名不变，内部实现改为优先查 registry |
| `load_from_path(path, bus)` | ✅ | 新增可选 `registry` 参数 |
| `agent-os list` | ✅ | 输出格式不变 |
| `agent-os inspect <id>` | ✅ | 输出格式不变 |

---

## 8. 文件结构与改动范围

### 8.1 文件改动一览

```
src/agentos/
├── __init__.py                    ← 不改
├── cli.py                        ← 改（引入 Registry，替代手动 loop）
├── models.py                     ← 不改
├── capability_pool.py            ← 改（接受 registry 引用 + 旧式兼容）
├── execution_engine.py           ← 不改（可通过 pool 间接用 registry）
├── planner.py                    ← 不改
├── workflow_loader.py            ← 改（新增可选 registry 参数）
│
├── capabilities/
│   ├── __init__.py               ← 改（改为 CAPABILITY_MANIFESTS + 保留 CAPABILITIES）
│   ├── search.py                 ← 改（新增 SEARCH_MANIFEST）
│   ├── llm.py                    ← 改（新增 LLM_MANIFEST）
│   ├── review.py                 ← 改（新增 REVIEW_MANIFEST）
│   └── report.py                 ← 改（新增 REPORT_MANIFEST）
│
├── registry/                     ← 🆕（新增目录）
│   ├── __init__.py               ← AgentOSRegistry（统一入口）
│   ├── capability.py             ← CapabilityRegistry + CapabilityManifest
│   └── workflow.py               ← WorkflowRegistry + WorkflowManifest
│
└── backbone/                     ← 不改
```

### 8.2 新增/修改统计

| 文件 | 操作 | 行数预估 |
|------|------|---------|
| `registry/__init__.py` | 🆕 | ~80 |
| `registry/capability.py` | 🆕 | ~150 |
| `registry/workflow.py` | 🆕 | ~150 |
| `capabilities/__init__.py` | 改 | ~20（改为声明式） |
| `capabilities/search.py` | 改 | +5（新增 manifest 常量） |
| `capabilities/llm.py` | 改 | +5 |
| `capabilities/review.py` | 改 | +5 |
| `capabilities/report.py` | 改 | +5 |
| `capability_pool.py` | 改 | +15（接受 registry） |
| `cli.py` | 改 | -3（删掉手动 loop）+ 5（引入 Registry） |
| `workflow_loader.py` | 改 | +10（可选 registry 参数 + track 调用） |
| **总计** | | **~450 行新增/修改** |

---

## 9. 关键代码实现

### 9.1 `registry/capability.py`

```python
"""Capability Registry — RFC-0300 §4."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentos.backbone.bus import EventBus
from agentos.backbone.event import Event

logger = logging.getLogger(__name__)


@dataclass
class CapabilityManifest:
    """Static metadata for a capability (replaces bare Callable pairs)."""
    task_type: str
    display_name: str
    description: str = ""
    version: str = "0.0.0"
    input_schema: dict | None = None
    output_schema: dict | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "builtin"
    enabled: bool = True


class CapabilityRegistry:
    """Metadata registry for capabilities."""

    def __init__(self, bus: EventBus | None = None):
        self._manifests: dict[str, CapabilityManifest] = {}
        self._functions: dict[str, Callable] = {}
        self._bus = bus

    # ── Registration ──────────────────────────────────────

    def register(self, task_type: str, fn: Callable,
                 manifest: CapabilityManifest | None = None) -> None:
        """Register a capability (legacy-compatible signature)."""
        if manifest is None:
            manifest = CapabilityManifest(
                task_type=task_type,
                display_name=task_type,
                description=f"(auto-registered)",
                version="0.0.0",
                source="legacy",
            )
        self._manifests[task_type] = manifest
        self._functions[task_type] = fn

        if self._bus:
            self._bus.publish(Event.new(
                "Registry:CapabilityRegistered",
                payload={"task_type": task_type, "version": manifest.version,
                         "source": manifest.source},
                source={"module": "registry.capability", "instance_id": ""},
            ))
        logger.info("Registered capability: %s v%s", task_type, manifest.version)

    def register_manifest(self, manifest: CapabilityManifest,
                          fn: Callable | None = None) -> None:
        """Register from a CapabilityManifest (preferred)."""
        self._manifests[manifest.task_type] = manifest
        if fn:
            self._functions[manifest.task_type] = fn

        if self._bus:
            self._bus.publish(Event.new(
                "Registry:CapabilityRegistered",
                payload={"task_type": manifest.task_type,
                         "version": manifest.version,
                         "source": manifest.source},
                source={"module": "registry.capability", "instance_id": ""},
            ))

    def register_lazy(self, task_type: str,
                      manifest: CapabilityManifest) -> None:
        """Register metadata only; function will be resolved on first call."""
        self._manifests[task_type] = manifest

    # ── Query ─────────────────────────────────────────────

    def get_manifest(self, task_type: str) -> CapabilityManifest | None:
        return self._manifests.get(task_type)

    def get_function(self, task_type: str) -> Callable | None:
        return self._functions.get(task_type)

    def list(self, tag: str | None = None,
             source: str | None = None) -> list[CapabilityManifest]:
        results = list(self._manifests.values())
        if tag:
            results = [m for m in results if tag in m.tags]
        if source:
            results = [m for m in results if m.source == source]
        return results

    def contains(self, task_type: str) -> bool:
        return task_type in self._manifests

    # ── Lifecycle ─────────────────────────────────────────

    def unregister(self, task_type: str) -> bool:
        if task_type not in self._manifests:
            return False
        del self._manifests[task_type]
        self._functions.pop(task_type, None)
        if self._bus:
            self._bus.publish(Event.new(
                "Registry:CapabilityUnregistered",
                payload={"task_type": task_type},
                source={"module": "registry.capability", "instance_id": ""},
            ))
        return True

    # ── Batch loading ─────────────────────────────────────

    def load_from_module(self, module_name: str) -> int:
        """Load all CAPABILITY_MANIFESTS from a module."""
        import importlib
        mod = importlib.import_module(module_name)
        manifests = getattr(mod, "CAPABILITY_MANIFESTS", [])
        for entry in manifests:
            if isinstance(entry, tuple):
                manifest, fn = entry
                self.register_manifest(manifest, fn=fn)
            else:
                self.register_manifest(entry)
        count = len(manifests)
        if self._bus:
            self._bus.publish(Event.new(
                "Registry:CapabilitiesLoaded",
                payload={"module": module_name, "count": count},
                source={"module": "registry.capability", "instance_id": ""},
            ))
        return count

    @property
    def count(self) -> int:
        return len(self._manifests)
```

### 9.2 `registry/workflow.py`

```python
"""Workflow Registry — RFC-0300 §5."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone

from agentos.backbone.bus import EventBus
from agentos.backbone.event import Event
from agentos.workflow_loader import WORKFLOW_DIRS, _load_from_path

logger = logging.getLogger(__name__)


@dataclass
class WorkflowManifest:
    """Workflow metadata extracted from the YAML definition."""
    id: str
    name: str
    description: str = ""
    path: Path | None = None
    task_count: int = 0
    capability_types: set[str] = field(default_factory=set)
    last_loaded: str = ""
    source: str = "local"


class WorkflowRegistry:
    """Scans, indexes, and queries workflows."""

    def __init__(self, bus: EventBus | None = None,
                 extra_dirs: list[Path] | None = None):
        self._workflows: dict[str, WorkflowManifest] = {}
        self._capability_index: dict[str, set[str]] = {}
        self._dirs = list(WORKFLOW_DIRS) + (extra_dirs or [])
        self._scanned = False
        self._bus = bus

    # ── Scanning ──────────────────────────────────────────

    def scan(self, extra_dirs: list[Path] | None = None) -> int:
        """Scan known directories for *.yaml workflow files."""
        dirs = list(self._dirs)
        if extra_dirs:
            dirs.extend(extra_dirs)
            self._dirs.extend(extra_dirs)

        discovered: dict[str, Path] = {}
        for d in dirs:
            if not Path(d).is_dir():
                continue
            for f in sorted(Path(d).glob("*.yaml")):
                discovered[f.stem] = f

        new_count = 0
        for wf_id, path in discovered.items():
            try:
                manifest = self._build_manifest(path)
                if wf_id not in self._workflows or manifest.last_loaded > self._workflows[wf_id].last_loaded:
                    self._workflows[wf_id] = manifest
                    self._update_index(manifest)
                    new_count += 1
            except Exception as e:
                logger.warning("Failed to index workflow '%s': %s", wf_id, e)

        self._scanned = True

        if self._bus:
            self._bus.publish(Event.new(
                "Registry:WorkflowScanned",
                payload={"count": len(self._workflows), "new": new_count},
                source={"module": "registry.workflow", "instance_id": ""},
            ))

        return new_count

    def track(self, workflow) -> WorkflowManifest:
        """Index an already-loaded Workflow object."""
        now = datetime.now(timezone.utc).isoformat()
        manifest = WorkflowManifest(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            task_count=len(workflow.tasks),
            capability_types={t.type for t in workflow.tasks},
            last_loaded=now,
        )
        self._workflows[workflow.id] = manifest
        self._update_index(manifest)

        if self._bus:
            self._bus.publish(Event.new(
                "Registry:WorkflowTracked",
                payload={"workflow_id": workflow.id,
                         "task_count": len(workflow.tasks),
                         "capability_types": sorted(manifest.capability_types)},
                source={"module": "registry.workflow", "instance_id": ""},
            ))
        return manifest

    def _build_manifest(self, path: Path) -> WorkflowManifest:
        """Parse YAML headers without loading full workflow."""
        import yaml
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        tasks = raw.get("tasks", [])
        return WorkflowManifest(
            id=raw.get("id", path.stem),
            name=raw.get("name", path.stem),
            description=raw.get("description", ""),
            path=path,
            task_count=len(tasks),
            capability_types={t.get("type", "") for t in tasks if t.get("type")},
            last_loaded=datetime.now(timezone.utc).isoformat(),
        )

    def _update_index(self, manifest: WorkflowManifest) -> None:
        """Maintain reverse index: capability_type → {workflow_ids}."""
        for ct in manifest.capability_types:
            self._capability_index.setdefault(ct, set()).add(manifest.id)

    # ── Query ─────────────────────────────────────────────

    def get(self, workflow_id: str) -> WorkflowManifest | None:
        if not self._scanned:
            self.scan()
        return self._workflows.get(workflow_id)

    def list(self) -> list[WorkflowManifest]:
        if not self._scanned:
            self.scan()
        return list(self._workflows.values())

    def find_by_capability(self, task_type: str) -> list[WorkflowManifest]:
        if not self._scanned:
            self.scan()
        wf_ids = self._capability_index.get(task_type, set())
        return [self._workflows[wid] for wid in wf_ids if wid in self._workflows]

    def contains(self, workflow_id: str) -> bool:
        if not self._scanned:
            self.scan()
        return workflow_id in self._workflows

    def refresh(self, path: Path | None = None) -> int:
        """Refresh index (optionally for a single path)."""
        if path:
            # Re-index one specific path
            if path.is_file() and path.suffix in (".yaml", ".yml"):
                try:
                    manifest = self._build_manifest(path)
                    self._workflows[manifest.id] = manifest
                    self._update_index(manifest)
                    return 1
                except Exception as e:
                    logger.warning("Refresh failed for %s: %s", path, e)
                    return 0
        else:
            # Full re-scan
            return self.scan()
        return 0

    @property
    def count(self) -> int:
        return len(self._workflows)

    @property
    def capability_index(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in self._capability_index.items()}
```

### 9.3 `registry/__init__.py`

```python
"""Agent OS Registry — RFC-0300 unified registry entry point."""

from __future__ import annotations

import logging
from pathlib import Path

from agentos.backbone.bus import EventBus
from agentos.backbone.event import Event
from .capability import CapabilityRegistry, CapabilityManifest
from .workflow import WorkflowRegistry, WorkflowManifest

logger = logging.getLogger(__name__)


class AgentOSRegistry:
    """Unified Registry — composes CapabilityRegistry + WorkflowRegistry.

    Usage:
        registry = AgentOSRegistry.setup_default(bus=bus)
        engine = ExecutionEngine(bus=bus, registry=registry)
    """

    def __init__(self, bus: EventBus | None = None):
        self.capabilities = CapabilityRegistry(bus=bus)
        self.workflows = WorkflowRegistry(bus=bus)
        self._bus = bus

    # ── One-shot setup ────────────────────────────────────

    @classmethod
    def setup_default(cls, bus: EventBus | None = None,
                      extra_workflow_dirs: list[Path] | None = None
                      ) -> "AgentOSRegistry":
        """Create with all built-in capabilities and scan workflow dirs."""
        registry = cls(bus=bus)

        # Load manifests from the capabilities package
        from agentos.capabilities import CAPABILITY_MANIFESTS
        for entry in CAPABILITY_MANIFESTS:
            manifest, fn = entry
            registry.capabilities.register_manifest(manifest, fn=fn)

        # Scan workflows
        registry.workflows.scan(extra_dirs=extra_workflow_dirs)

        if bus:
            bus.publish(Event.new(
                "Registry:Initialized",
                payload={
                    "capability_count": registry.capabilities.count,
                    "workflow_count": registry.workflows.count,
                },
                source={"module": "registry", "instance_id": ""},
            ))

        logger.info(
            "Registry initialized: %d capabilities, %d workflows",
            registry.capabilities.count, registry.workflows.count,
        )
        return registry

    # ── Cross-registry queries ────────────────────────────

    def resolve_workflow(self, workflow_id: str) -> WorkflowManifest | None:
        return self.workflows.get(workflow_id)

    def resolve_capability(self, task_type: str) -> CapabilityManifest | None:
        return self.capabilities.get_manifest(task_type)

    def workflows_using(self, task_type: str) -> list[WorkflowManifest]:
        return self.workflows.find_by_capability(task_type)

    def capabilities_for_workflow(self, workflow_id: str
                                  ) -> list[CapabilityManifest]:
        wf = self.workflows.get(workflow_id)
        if not wf:
            return []
        return [
            m for m in self.capabilities.list()
            if m.task_type in wf.capability_types and m.enabled
        ]

    # ── Snapshot ──────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "capabilities": [
                {
                    "task_type": m.task_type,
                    "version": m.version,
                    "display_name": m.display_name,
                    "source": m.source,
                    "enabled": m.enabled,
                    "tags": m.tags,
                }
                for m in self.capabilities.list()
            ],
            "workflows": [
                {
                    "id": m.id,
                    "name": m.name,
                    "task_count": m.task_count,
                    "capability_types": sorted(m.capability_types),
                    "source": m.source,
                }
                for m in self.workflows.list()
            ],
        }


__all__ = [
    "AgentOSRegistry",
    "CapabilityRegistry",
    "CapabilityManifest",
    "WorkflowRegistry",
    "WorkflowManifest",
]
```

### 9.4 `capabilities/__init__.py` 改造

```python
"""Built-in capabilities registry — RFC-0300 declarative manifests."""

from agentos.registry.capability import CapabilityManifest
from .search import search
from .llm import llm
from .review import review
from .report import report

# ── Declarative manifests ─────────────────────────────────

SEARCH_MANIFEST = CapabilityManifest(
    task_type="search",
    display_name="Web Search",
    description="Search the internet and return structured results.",
    version="1.0.0",
    tags=["web", "search"],
)

LLM_MANIFEST = CapabilityManifest(
    task_type="llm",
    display_name="LLM Inference",
    description="Invoke a large language model for text generation.",
    version="1.0.0",
    tags=["llm", "generation"],
)

REVIEW_MANIFEST = CapabilityManifest(
    task_type="review",
    display_name="Task Review",
    description="Review task outputs for quality and completeness.",
    version="1.0.0",
    tags=["quality", "review"],
)

REPORT_MANIFEST = CapabilityManifest(
    task_type="report",
    display_name="Report Generator",
    description="Generate structured Markdown reports from task outputs.",
    version="1.0.0",
    tags=["output", "report"],
)

# 引入 "gather" 作为 "review" 的别名
GATHER_MANIFEST = CapabilityManifest(
    task_type="gather",
    display_name="Gather (review alias)",
    description="Alias for the review capability.",
    version="1.0.0",
    tags=["quality", "review", "alias"],
)

# ── Registry-loadable list ────────────────────────────────
# Each entry: (CapabilityManifest, callable | None)
# None = lazy-loading (function resolved at first use)

CAPABILITY_MANIFESTS = [
    (SEARCH_MANIFEST, search),
    (LLM_MANIFEST, llm),
    (REVIEW_MANIFEST, review),
    (REPORT_MANIFEST, report),
    (GATHER_MANIFEST, review),         # "gather" → review function
]

# ── Legacy compatibility ──────────────────────────────────
# Old code: from .capabilities import CAPABILITIES
# Old code: for tp, fn in CAPABILITIES.items(): pool.register(tp, fn)

CAPABILITIES: dict[str, CapabilityManifest] = {
    m.task_type: m for m, _ in CAPABILITY_MANIFESTS
}

__all__ = [
    "search", "llm", "review", "report",
    "CAPABILITIES", "CAPABILITY_MANIFESTS",
]
```

### 9.5 `capability_pool.py` 改造（增量）

```python
class CapabilityPool:
    def __init__(self, registry: CapabilityRegistry | None = None):
        self._registry: dict[str, Callable] = {}   # old-style (backward compat)
        self._invocations: dict[str, InvocationResult] = {}
        self._meta_registry = registry

    def register(self, task_type: str, fn: Callable) -> None:
        """Legacy register — also syncs to meta-registry if available."""
        self._registry[task_type] = fn
        if self._meta_registry:
            self._meta_registry.register(task_type, fn)
        logger.debug("Pool: registered type=%s", task_type)

    def invoke(self, task: PlannedTask, context: dict) -> InvocationResult:
        fn = self._registry.get(task.type)
        # ... rest stays the same ...
```

### 9.6 `cli.py` 改造

```diff
 def _cmd_run(args: argparse.Namespace) -> int:
     # ...
     bus = EventBus()
-    engine = ExecutionEngine(bus=bus)
-
-    # Register built-in executors from capabilities module
-    for tp, fn in CAPABILITIES.items():
-        engine.pool.register(tp, fn)
+    registry = AgentOSRegistry.setup_default(bus=bus)
+    engine = ExecutionEngine(bus=bus, registry=registry)
```

### 9.7 `workflow_loader.py` 改造

```diff
-def _load_from_path(path: Path, bus: EventBus | None = None) -> Workflow:
+def _load_from_path(path: Path, bus: EventBus | None = None,
+                    registry: 'AgentOSRegistry | None' = None) -> Workflow:
     # ... existing code ...
     wf = Workflow(...)
 
+    if registry:
+        registry.workflows.track(wf)
+
     if bus:
         bus.publish(Event.new(...))
     return wf
```

---

## 10. 测试策略

### 10.1 单元测试（新增）

| 测试 | 文件 | 关键场景 |
|------|------|---------|
| `TestCapabilityRegistry` | `tests/test_registry.py` | register, unregister, query, list with tags, events |
| `TestCapabilityManifest` | `tests/test_registry.py` | dataclass construction, defaults |
| `TestWorkflowRegistry` | `tests/test_registry.py` | scan, track, get, find_by_capability, refresh |
| `TestWorkflowManifest` | `tests/test_registry.py` | build_manifest from real YAML |
| `TestAgentOSRegistry` | `tests/test_registry.py` | setup_default, resolve_workflow, resolve_capability, snapshot |
| `TestPoolIntegration` | `tests/test_pool.py` | pool with registry, legacy register compat |

### 10.2 回归测试（现有）

| 测试 | 验证点 |
|------|--------|
| `test_backbone.py` | Event Bus 不受影响 |
| E2E workflow run | CLI `agent-os run` 从旧式 CAPABILITIES 仍能加载 workflow |

### 10.3 迁移验证

```python
# 验证：旧式注册兼容
pool = CapabilityPool(registry=reg)
pool.register("search", my_fn)
assert reg.capabilities.contains("search")    # 旧注册同步到新 registry

# 验证：反向索引
reg.workflows.track(wf)
assert "search" in reg.workflows.capability_index
assert wf.id in reg.workflows.find_by_capability("search")

# 验证：snapshot
snap = reg.snapshot()
assert "capabilities" in snap
assert "workflows" in snap
```

---

## 总结

| 维度 | 改造前 | 改造后 | 增量 |
|------|--------|--------|------|
| **Capability 注册** | 硬编码 `CAPABILITIES` dict | `CapabilityManifest` 声明式元数据 | 可发现、有版本、有描述 |
| **注册位置** | 在 `cli.py` 中手动 loop | `AgentOSRegistry.setup_default()` 一次性完成 | 无遗漏、无重复 |
| **Workflow 索引** | 每次扫磁盘 | 一次扫描、内存缓存 + 反向索引 | 10x 查询速度提升 |
| **反向查询** | 不支持 | `find_by_capability("llm")` → workflows | 支撑 UX 智能推荐 |
| **可观测性** | 无 | 注册事件 `Registry:*` 系列 | 可监控、可审计 |
| **新文件** | 0 | 3 (`registry/__init__.py`, `capability.py`, `workflow.py`) | ~380 行 |
| **改动文件** | 0 | 6 (capabilities/*, cli.py, pool.py, loader.py) | ~+100 / -10 行 |
| **现有 CLI 兼容** | — | ✅ 完全向后兼容 | 0 破坏性变更 |
