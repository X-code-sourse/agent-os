# Agent OS Engine 改造方案：Event Bus 集成 · Capability Pool · Task 状态机追踪

**作者:** Backend Architect  
**日期:** 2026-07-20  
**状态:** Design Proposal  
**目标版本:** agent-os P1 → P2 (增量改造，保持 CLI 接口不变)

---

## 目录

1. [现状分析](#1-现状分析)
2. [Event Bus 集成：Engine 改为事件驱动](#2-event-bus-集成engine-改为事件驱动)
3. [Capability Pool 接口设计](#3-capability-pool-接口设计)
4. [Task 状态机追踪（简化 6 态）](#4-task-状态机追踪简化-6-态)
5. [文件结构与改动范围](#5-文件结构与改动范围)
6. [增量迁移策略](#6-增量迁移策略)
7. [附录：关键代码伪代码](#7-附录关键代码伪代码)

---

## 1. 现状分析

### 1.1 当前 P1 架构（已验证 E2E）

```
CLI (cli.py)
  ├── EventBus (event_bus.py)       ← 简单内存 pub/sub + SQLite Store
  ├── WorkflowLoader                 ← 从 YAML 加载
  ├── Planner                        ← 拓扑排序 + Rule 注入
  ├── ExecutionEngine                ← 直接调用 TaskExecutor（dict 注册）
  │     └── TaskExecutor             ← dict[str, Callable] 直接调函数
  ├── Reviewer                       ← 质量检查
  └── Reporter                       ← Markdown 报告
```

### 1.2 现有模块的关键细节

| 模块 | 文件 | 当前能力 | 缺失 |
|------|------|---------|------|
| **EventBus** | `event_bus.py` | 内存 pub/sub + SQLite 持久化 | Engine 只用了 `publish()`，无订阅回调驱动逻辑 |
| **Event 模型** | `models.py:Event` | 简单 4 字段（id/type/source/data） | 无 RFC-0500 标准信封（version/metadata/context） |
| **ExecutionEngine** | `execution_engine.py` | DAG 调度 + 同步执行 | 通过 `_registry` 直接调函数，无 Pool，状态仅有 3 态 |
| **TaskExecutor** | `execution_engine.py` | `dict[str, fn]` 注册表 | 无并发控制、无健康检查、无 invoke/cancel/status 接口 |
| **TaskResult** | `models.py` | status: `pending\|running\|completed\|failed` | 无状态历史、无运行耗时、无重试追踪 |
| **Backbone** | `reference/src/agentos/backbone/` | 完整的 RFC-0500 实现（未接入 P1） | 未被 P1 使用 |

### 1.3 参考实现的 Backbone（已存在但未使用）

路径: `C:\Users\haiha\agent-os\reference\src\agentos\backbone\`

| 文件 | 内容 | 是否直接可用 |
|------|------|------------|
| `event.py` | RFC-0500 标准 Event 信封（frozen dataclass） | 可直接导入 |
| `bus.py` | 带 at-least-once 和 dead-letter 的 Event Bus | 可直接导入 |
| `store.py` | SQLite Event Store + Replay API + Snapshot | 可直接导入 |
| `schema.py` | Schema Registry + 发布时验证 | 可直接导入 |

**关键决策：直接复用参考实现的 backbone 模块，不重造轮子。**

---

## 2. Event Bus 集成：Engine 改为事件驱动

### 2.1 设计目标

1. Engine 不再直接调用 executor 函数，改为**发布事件 → 订阅者处理 → 回传结果事件**
2. 所有 Task 状态转换都通过 Event Bus 发布（RFC-0001 §6.1）
3. 复用 `reference/src/agentos/backbone/` 的 RFC-0500 实现
4. CLI 接口完全不变

### 2.2 事件流

```
Engine.execute(plan)
  │
  ├─ 为每个 Task 发布 Task:Created
  │     payload: { task_id, type, execution_id }
  │
  ├─ (DependencyTracker 判断依赖就绪后)
  │     ↓
  ├─ 发布 Task:Queued
  │     payload: { task_id, queue_position }
  │
  ├─ (Scheduler 出队后)
  │     ↓
  ├─ 发布 Task:Running
  │     payload: { task_id, capability_id }
  │
  ├─ (CapabilityPool 执行完成)
  │     ↓
  ├─ 发布 Task:Completed 或 Task:Failed
  │     payload: { task_id, output/error, duration_ms }
  │
  └─ 全部完成后发布 Execution:Completed / Execution:Failed
        payload: { execution_id, task_summary, status }
```

### 2.3 事件类型映射

| RFC-0001 标准事件 | 当前 P1 事件 | 改动 |
|-------------------|-------------|------|
| `Task:Created` | 无 | **新增** |
| `Task:Queued` | 无 | **新增** |
| `Task:Running` | `task.started` | 改名 |
| `Task:Completed` | `task.completed` | 改名 |
| `Task:Failed` | `task.failed` | 改名 |
| `Execution:Created` | 无 | **新增** |
| `Execution:Running` | 无 | **新增** |
| `Execution:Completed` | `execution.finished` | 改名 |
| `Execution:Failed` | `execution.finished(status=failed)` | 拆分 |
| `workflow.loaded` | `workflow.loaded` | 保留（Planner/WorkflowLoader 已发） |
| `plan.ready` | `plan.ready` | 保留（Planner 已发） |

### 2.4 集成方案：最小改动路径

保持现有 `ExecutionEngine` 类结构，仅修改内部实现以发布标准事件。

**改造后的 Engine.schedule_and_execute() 流程：**

```python
class ExecutionEngine:
    def execute(self, plan, context=None):
        # 1. 发布 Execution:Created → Execution:Running
        # 2. 初始化 DependencyTracker（基于 plan.dag）
        # 3. 为每个 Task 发布 Task:Created
        # 4. 对根节点发布 Task:Queued
        # 5. 主循环（同步 v1）：
        #     5a. 出队 → 发布 Task:Running
        #     5b. 通过 CapabilityPool 执行
        #     5c. 成功 → 发布 Task:Completed
        #     5d. 失败 → 发布 Task:Failed
        #     5e. DependencyTracker 推进后续 Task
        # 6. 全部完成 → 发布 Execution:Completed/Failed
```

**关键：使用参考实现的 `backbone.event.Event` 替代 `models.Event`。**

```python
# 适配器：从 P1 的 Event 过渡到标准 Event
# engine/publisher.py (新增)
from agentos.backbone.event import Event as StdEvent

def make_std_event(event_type, payload, source, execution_id=None):
    return StdEvent.new(
        event_type=event_type,
        payload=payload,
        source={"module": source, "instance_id": "engine-001"},
        context={"execution_id": execution_id} if execution_id else {},
    )
```

### 2.5 保留与兼容

- `models.Event` 保留给 WorkflowLoader / Planner 等模块临时使用
- Engine 内部使用标准 `backbone.event.Event`
- Event Bus 实例接收两种事件类型均可（非严格模式）
- 后期逐步迁移所有模块到标准事件

---

## 3. Capability Pool 接口设计

### 3.1 设计目标

1. **替代**当前的 `TaskExecutor._registry` dict
2. 提供 `invoke / cancel / status` 三方法接口（RFC-0200 §5.2）
3. 支持并发限制和排队（RFC-0203 §4）
4. CLI 注册 executors 的接口不变（保持 `engine.executor.register("llm", fn)` 语法糖）

### 3.2 CapabilityPool 类接口

```python
class CapabilityPool:
    """Capability Pool — RFC-0200 §5 + RFC-0203 §3 的 v1 简化实现。

    v1 特性（P2 里程碑）：
    - invoke: 同步执行（内部函数调用），支持超时
    - cancel: 标记取消（同步执行无法强制中断）
    - status: 查询实例状态
    - 简单并发限制（per-capability）

    后续迭代（P3+）：
    - 多实例池
    - 健康检查
    - 异步/线程执行
    - 优先队列
    """

    def __init__(self, concurrency_limits: dict[str, int] | None = None):
        self._instances: dict[str, CapabilityInstance] = {}
        self._limits = concurrency_limits or {}
        self._active_counts: dict[str, int] = defaultdict(int)

    def register(self, capability_id: str, executor_fn: Callable,
                 max_concurrent: int = 5) -> None:
        """注册一个 capability 实例（当前同步模式）。"""
        ...

    def invoke(self, task_id: str, capability_id: str,
               input: dict, context: dict, deadline: str | None = None
               ) -> InvocationResult:
        """同步调用 capability。

        Returns InvocationResult (success | partial | error).
        如果并发限制已满 → raise PoolBusyError。
        """
        ...

    def cancel(self, invocation_id: str) -> CancelResult:
        """标记取消（同步模式下不强制中断）。"""
        ...

    def status(self, capability_id: str) -> PoolStatus:
        """返回 capability 实例的状态和统计。"""
        ...
```

### 3.3 返回值类型

```python
@dataclass
class InvocationResult:
    status: str                    # "success" | "partial" | "error"
    output: Any = None
    error: dict | None = None      # {code, message, retryable}
    metrics: dict = field(default_factory=dict)  # tokens, latency_ms, cost
    completeness: float = 1.0      # 0.0–1.0（partial 时）
    usable_for: list[str] = field(default_factory=list)

@dataclass
class CancelResult:
    status: str                    # "cancelled" | "cancelling"
    reason: str = ""
    work_saved: dict = field(default_factory=dict)

@dataclass
class PoolStatus:
    capability_id: str
    active_invocations: int
    queued_invocations: int
    max_concurrent: int
    healthy: bool

class PoolBusyError(Exception):
    """并发限制已达到，无法接受新的 invoke 请求。"""
```

### 3.4 Engine 中的集成点

```python
class ExecutionEngine:
    def __init__(self, bus=None):
        self.bus = bus
        self.pool = CapabilityPool()   # ← 替换 TaskExecutor
        # 兼容旧接口：engine.executor.register(...)
        self.executor = _LegacyAdapter(self.pool)


class _LegacyAdapter:
    """使老代码 engine.executor.register(type, fn) 能继续工作。

    将 (task_type → fn) 注册转为 capability_id=task_type 的注册。
    """
    def __init__(self, pool: CapabilityPool):
        self._pool = pool

    def register(self, task_type: str, fn: Callable) -> None:
        self._pool.register(task_type, fn)
```

### 3.5 CLI 中注册 executors 的兼容路径

```python
# cli.py — 几乎不变
engine = ExecutionEngine(bus=bus)
engine.executor.register("search", _exec_search)   # 通过 _LegacyAdapter
engine.executor.register("llm", _exec_llm)
# ...
```

---

## 4. Task 状态机追踪（简化 6 态）

### 4.1 设计目标

1. 从当前的 3 态（running/completed/failed）扩展到**可追踪的 6 态**
2. 每个 Task 记录完整状态历史（state_history）
3. 支持 Execution 级别的状态汇总
4. 保持与现有 `models.TaskResult` / `models.ExecutionResult` 的**向后兼容**

### 4.2 状态定义

```
简化状态机（RFC-0001 §3 的子集 → P2 实现）：

  [Created] ──→ [Queued] ──→ [Running] ──→ [Completed]
                                      │
                                      └──→ [Failed]
                                              │
                                              └──→ [RetryQueued] ──→ [Queued]（循环）

状态       | 是否为终点 | 说明
Created    | 否        | Task 已实例化，尚未调度
Queued     | 否        | 在调度队列中等待
Running    | 否        | 正在执行
Completed  | 是        | 成功完成
Failed     | 否        | 失败（可能重试）
RetryQueued| 否        | 等待重试，之后回到 Queued
```

### 4.3 数据模型扩展

```python
# models.py — 新增/修改

@dataclass
class StateTransition:
    """单次状态转换记录。"""
    from_state: str
    to_state: str
    at: datetime
    reason: str = ""


@dataclass
class TaskResult:
    """任务执行结果 — 扩展状态追踪。"""
    task_id: str
    # 当前状态（保持兼容）
    status: str = "pending"       # pending | created | queued | running | completed | failed | retry_queued

    # === 新增字段 ===
    state_history: list[StateTransition] = field(default_factory=list)
    state: str = "created"        # RFC-0001 标准状态名
    retry_count: int = 0
    max_retries: int = 3
    duration_ms: int | None = None

    # 原有字段
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def transition_to(self, new_state: str, reason: str = "") -> None:
        """记录状态转换并发布事件（通过外部 EventBus）。"""
        transition = StateTransition(
            from_state=self.state,
            to_state=new_state,
            at=datetime.now(timezone.utc),
            reason=reason,
        )
        self.state_history.append(transition)
        self.state = new_state


@dataclass
class ExecutionResult:
    """执行结果 — 扩展状态汇总。"""
    workflow_id: str
    task_results: dict[str, TaskResult] = field(default_factory=dict)
    status: str = "pending"       # pending | running | completed | partial | failed

    # === 新增 ===
    state: str = "created"        # created | resolving | running | global_review | completed | failed
    state_history: list[StateTransition] = field(default_factory=list)

    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def task_summary(self) -> dict:
        """RFC-0001 §5.2 格式的任务汇总。"""
        total = len(self.task_results)
        completed = sum(1 for t in self.task_results.values() if t.state == "completed")
        failed = sum(1 for t in self.task_results.values() if t.state == "failed")
        running = sum(1 for t in self.task_results.values() if t.state == "running")
        pending = sum(1 for t in self.task_results.values() if t.state in ("created", "queued"))
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
        }
```

### 4.4 兼容性保证

| 现有代码使用方式 | 兼容？ | 说明 |
|-----------------|--------|------|
| `tr.status == "completed"` | ✅ | `status` 字段依然存在 |
| `tr.error` | ✅ | 不变 |
| `tr.output` | ✅ | 不变 |
| `result.status == "running"` | ✅ | `ExecutionResult.status` 依然存在 |
| `tr.started_at / completed_at` | ✅ | 不变 |
| 新增 `tr.state` | ✅ | 新字段，不影响旧代码 |
| 新增 `tr.state_history` | ✅ | 新字段 |
| 新增 `tr.task_summary` | ✅ | 新 property |

---

## 5. 文件结构与改动范围

### 5.1 文件改动一览

```
agent-os-p1/agent_os/
├── __init__.py              ← 不改（只 export 版本号）
├── models.py                ← 改（扩展 TaskResult/ExecutionResult + 新增类型）
├── event_bus.py             ← 不改（兼容层，继续提供给外部模块使用）
├── execution_engine.py      ← 改（引入 CapabilityPool + 标准事件 + 6 态追踪）
├── capability_pool.py       ← 新增（CapabilityPool 类）
├── planner.py               ← 不改（保留 plan.ready 事件）
├── reviewer.py              ← 不改（保留原有 check 逻辑）
├── reporter.py              ← 不改（保持 report 格式）
├── workflow_loader.py       ← 不改（保留 workflow.loaded 事件）
├── cli.py                   ← 不改（保持 CLI 接口不变）
└── task_executors/
    └── __init__.py           ← 不改（空的 __init__，后续可放 executor 实现）
```

### 5.2 新增文件

| 文件 | 内容 | 行数预估 |
|------|------|---------|
| `capability_pool.py` | `CapabilityPool` 类 + `InvocationResult` / `CancelResult` / `PoolStatus` / `PoolBusyError` | ~120 行 |
| `publisher.py` | 事件发布辅助函数（`make_std_event`、`publish_transition`） | ~50 行 |

### 5.3 `models.py` 的精确改动

```diff
# 新增 dataclass:
+ @dataclass
+ class StateTransition:
+     from_state: str
+     to_state: str
+     at: datetime
+     reason: str = ""

# 修改 TaskResult:
  @dataclass
  class TaskResult:
      task_id: str
      status: str = "pending"                    # 保留
+     state: str = "created"                     # 新增
+     state_history: list[StateTransition] = field(default_factory=list)
+     retry_count: int = 0
+     max_retries: int = 3
+     duration_ms: int | None = None
+     def transition_to(self, new_state: str, reason: str = "") -> None: ...
      output: Any = None
      error: str | None = None
      started_at: datetime | None = None
      completed_at: datetime | None = None

# 修改 ExecutionResult:
  @dataclass
  class ExecutionResult:
      workflow_id: str
      task_results: dict[str, TaskResult] = field(default_factory=dict)
      status: str = "pending"
+     state: str = "created"
+     state_history: list[StateTransition] = field(default_factory=list)
      started_at: datetime | None = None
      completed_at: datetime | None = None
+     @property
+     def task_summary(self) -> dict: ...
```

### 5.4 `execution_engine.py` 的精确改动

```
改动类型：重构（引入 CapabilityPool + 标准事件 + 状态追踪）
不改动：execute() 签名、__init__ 签名、CLI 调用路径

具体变更：
1. __init__:
   - 用 CapabilityPool 替代 TaskExecutor
   - 添加 _LegacyAdapter 兼容层
   - 保留 self.bus 引用

2. execute():
   - 步骤 0: 发布 Execution:Created
   - 步骤 1: 拓扑排序（复用已有逻辑）
   - 步骤 2: 为每个 Task 初始化 TaskResult（state="created"，发布 Task:Created）
   - 步骤 3: 根节点 → 发布 Task:Queued
   - 步骤 4: 主循环（同步）：
       - 出队 → 发布 Task:Running
       - pool.invoke() → 取代直接 executor.execute()
       - 成功 → 发布 Task:Completed
       - 失败 → 发布 Task:Failed（根据 retry 策略可走 Task:RetryQueued）
   - 步骤 5: 发布 Execution:Completed/Failed

3. 新增方法:
   - _publish_std_event(event_type, payload)
   - _transition_task(task_id, from_state, to_state, reason)
   - _transition_execution(from_state, to_state)
```

---

## 6. 增量迁移策略

### 6.1 阶段划分

```
Phase 1 (当前 P1): [已完成]
  - 同步 DAG 调度
  - 3 态追踪
  - 直接函数调用
  - 简单事件发布
  - CLI E2E 验证通过

Phase 2 (本次设计): [P2 里程碑]
  ├── Event Bus 集成
  │     └── Engine 发布标准 RFC-0001 事件（Task:Created..Failed）
  ├── Capability Pool
  │     ├── CapabilityPool 类替代 TaskExecutor dict
  │     └── invoke/cancel/status 接口
  └── State Machine
        ├── 6 态追踪（Created→Queued→Running→Completed/Failed→RetryQueued）
        └── state_history 记录

Phase 3 (未来):
  ├── 异步 Execution Engine（线程/协程）
  ├── Local Reviewer 作为事件订阅者
  ├── 真正的 replan 协议
  ├── 多实例 Capability Pool
  └── Event Store 状态恢复
```

### 6.2 向后兼容保证清单

| 检查点 | 保证 |
|--------|------|
| CLI 命令结构 | 不变（`agent-os run <wf> --query "..."`） |
| CLI 输出格式 | 不变（Markdown report + 返回值） |
| 注册 executor | 不变（`engine.executor.register(type, fn)` 通过 adapter 继续工作） |
| `ExecutionEngine.__init__` 签名 | 不变（`bus=None`） |
| `ExecutionEngine.execute()` 签名 | 不变（`plan, context=None`） |
| `models.Event` | 保留（WorkflowLoader/Planner 继续使用） |
| `TaskResult.status` | 保留（`"completed"` / `"failed"` 等值不变） |
| `ExecutionResult.status` | 保留 |
| YAML workflow 格式 | 不变 |
| 现有测试 | 应全部通过（需确认） |

### 6.3 迁移风险与缓解措施

| 风险 | 概率 | 缓解措施 |
|------|------|---------|
| 事件类型改名破坏下游订阅者 | 低 | P1 中只有 CLI debug 日志订阅了事件 |
| models.py 新增字段破坏 pickle | 低 | 仅 Python dict/serialize，无 pickle |
| CapabilityPool 性能开销 | 低 | v1 同步模式，额外成本仅方法调用 |
| Engine 代码行数增长 | 中 | 保持函数原子性，每个阶段 ≤50 行新增 |

---

## 7. 附录：关键代码伪代码

### 7.1 改造后的 `ExecutionEngine.execute()`

```python
def execute(self, plan: Plan, context: dict | None = None) -> ExecutionResult:
    ctx = context or {}
    now = datetime.now(timezone.utc)

    # ── 初始化 Execution ──────────────────────────────────
    result = ExecutionResult(
        workflow_id=plan.workflow_id,
        status="running",
        state="running",
        started_at=now,
    )
    result.state_history.append(StateTransition("created", "running", now))
    self._publish_std("Execution:Running", {"workflow_id": plan.workflow_id})

    task_map = {t.id: t for t in plan.tasks}
    outputs: dict[str, Any] = {}
    successors = self._build_successors(plan)

    # ── DAG 状态追踪 ──────────────────────────────────────
    ready: deque[str] = deque()
    in_degree = {t.id: len(t.depends_on) for t in plan.tasks}
    running: dict[str, PlannedTask] = {}
    completed_or_failed: set[str] = set()

    # 初始化所有 Task
    for t in plan.tasks:
        tr = TaskResult(task_id=t.id, state="created",
                        started_at=tr.started_at or now)
        result.task_results[t.id] = tr
        self._publish_std("Task:Created", {
            "task_id": t.id, "type": t.type,
            "execution_id": plan.workflow_id,
        })

    # 根节点入队
    for t in plan.tasks:
        if in_degree[t.id] == 0:
            ready.append(t.id)
            tr = result.task_results[t.id]
            tr.transition_to("queued")
            self._publish_std("Task:Queued", {
                "task_id": t.id, "queue_position": len(ready),
            })

    # ── 主调度循环 ────────────────────────────────────────
    while ready or running:
        while ready:
            task_id = ready.popleft()
            task = task_map[task_id]
            running[task_id] = task
            tr = result.task_results[task_id]
            tr.transition_to("running")
            tr.started_at = datetime.now(timezone.utc)
            self._publish_std("Task:Running", {
                "task_id": task_id, "type": task.type,
            })

            try:
                # 通过 CapabilityPool 执行
                inv_result = self.pool.invoke(
                    task_id=task_id,
                    capability_id=task.type,
                    input={**ctx, **outputs},
                    context={},
                )
                tr.output = inv_result.output
                tr.status = "completed"
                tr.state = "completed"
                tr.completed_at = datetime.now(timezone.utc)
                tr.duration_ms = 0  # 同步模式下暂不计算
                tr.transition_to("completed")
                outputs[task_id] = inv_result.output
                self._publish_std("Task:Completed", {
                    "task_id": task_id, "status": "completed",
                })

            except PoolBusyError:
                # 并发限制，重新入队
                tr.transition_to("queued", "pool_busy")
                ready.appendleft(task_id)   # 重试
                continue

            except Exception as e:
                tr.error = str(e)
                tr.completed_at = datetime.now(timezone.utc)
                tr.transition_to("failed", str(e))

                if tr.retry_count < tr.max_retries:
                    tr.retry_count += 1
                    tr.transition_to("retry_queued",
                                     f"retry {tr.retry_count}/{tr.max_retries}")
                    ready.append(task_id)
                    self._publish_std("Task:RetryQueued", {
                        "task_id": task_id,
                        "retry_attempt": tr.retry_count,
                        "max_retries": tr.max_retries,
                    })
                else:
                    self._publish_std("Task:Failed", {
                        "task_id": task_id, "error": str(e),
                        "retry_count": tr.retry_count,
                    })

            completed_or_failed.add(task_id)
            del running[task_id]

            # 推进后继节点
            for succ_id in successors.get(task_id, []):
                in_degree[succ_id] -= 1
                if in_degree[succ_id] == 0 and succ_id not in completed_or_failed:
                    ready.append(succ_id)
                    result.task_results[succ_id].transition_to("queued")

    # ── 汇总 Execution 状态 ────────────────────────────────
    failed = [r for r in result.task_results.values()
              if r.state == "failed"]
    if failed:
        result.status = "partial" if len(failed) < len(result.task_results) else "failed"
        result.state = "failed"
    else:
        result.status = "completed"
        result.state = "completed"

    result.completed_at = datetime.now(timezone.utc)
    result.transition_to(result.state)
    self._publish_std("Execution:Completed" if result.state == "completed"
                      else "Execution:Failed", {
        "workflow_id": plan.workflow_id,
        "status": result.status,
        "task_summary": result.task_summary,
    })
    return result
```

### 7.2 CapabilityPool 核心实现

```python
class CapabilityPool:
    def __init__(self, concurrency_limits: dict[str, int] | None = None):
        self._instances: dict[str, CapabilityInstance] = {}
        self._limits = concurrency_limits or {}
        self._active: dict[str, int] = defaultdict(int)

    def register(self, capability_id: str, fn: Callable, max_concurrent: int = 5):
        self._instances[capability_id] = CapabilityInstance(
            id=capability_id, fn=fn,
            max_concurrent=max_concurrent,
        )

    def invoke(self, task_id: str, capability_id: str,
               input: dict, context: dict,
               deadline: str | None = None) -> InvocationResult:
        instance = self._instances.get(capability_id)
        if not instance:
            return InvocationResult(
                status="error",
                error={"code": "capability_not_found",
                       "message": f"No capability '{capability_id}'",
                       "retryable": False},
            )
        if self._active[capability_id] >= instance.max_concurrent:
            raise PoolBusyError(
                f"Capability '{capability_id}' at limit "
                f"({instance.max_concurrent})"
            )
        self._active[capability_id] += 1
        try:
            output = instance.fn(input, context)
            return InvocationResult(status="success", output=output)
        except Exception as e:
            return InvocationResult(
                status="error",
                error={"code": "execution_error",
                       "message": str(e),
                       "retryable": True},
            )
        finally:
            self._active[capability_id] -= 1

    def cancel(self, invocation_id: str) -> CancelResult:
        # v1 同步模式：无法强制中断
        return CancelResult(status="cancelled", reason="sync_mode_noop")

    def status(self, capability_id: str) -> PoolStatus:
        instance = self._instances.get(capability_id)
        if not instance:
            raise ValueError(f"Unknown capability: {capability_id}")
        return PoolStatus(
            capability_id=capability_id,
            active_invocations=self._active[capability_id],
            queued_invocations=0,
            max_concurrent=instance.max_concurrent,
            healthy=True,
        )
```

### 7.3 事件发布辅助函数

```python
# publisher.py (新增)

from agentos.backbone.event import Event as StdEvent

def make_std_event(event_type: str, payload: dict,
                   source: str = "execution_engine",
                   execution_id: str | None = None) -> StdEvent:
    return StdEvent.new(
        event_type=event_type,
        payload=payload,
        source={"module": source, "instance_id": "engine-001"},
        context={"execution_id": execution_id} if execution_id else {},
    )

def publish_transition(bus, event_type: str, payload: dict,
                       execution_id: str | None = None) -> None:
    """发布标准状态转换事件。兼容新旧两种 Event 类型。"""
    event = make_std_event(event_type, payload,
                           execution_id=execution_id)
    bus.publish(event)
```

---

## 总结

| 维度 | 当前 P1 | 改造后 P2 | 增量 |
|------|---------|-----------|------|
| **事件** | `task.started` 等简单事件 | `Task:Running` 等 RFC-0001 标准事件 | +6 事件类型 |
| **事件信封** | 简单 4 字段 | 复用参考实现的 RFC-0500 标准信封 | 可选迁移 |
| **Capability** | `dict[str, fn]` | `CapabilityPool.invoke/cancel/status` | 新增 1 文件 |
| **状态** | 3 态（run/completed/failed） | 6 态（created/queued/running/completed/failed/retry_queued）+ history | +3 态 |
| **文件数** | 6 个 .py | 8 个 .py（+2） | +2 |
| **CLI 兼容** | — | 完全向后兼容 | 0 改动 |
| **现有测试** | — | 应全部通过 | 预期无回归 |
