# Agent OS 参考实现代码审查报告

**审查范围:** `reference/src/agentos/` — 15 个文件, ~1784 行 Python  
**审查依据:** CONSTITUTION.md, RFC-0001, RFC-0101, RFC-0102, RFC-0200, RFC-0500, schemas/execution/plan.json  
**严重性分级:** S1 = 架构违规, S2 = 规范偏离, S3 = 代码质量  

---

## 🔴 S1 — 架构违规 (Constitution Violations)

### S1-1 [A1] Kernel 有状态 — 所有事件仅存在于内存, 未持久化到 Data Plane

**文件:** `cli.py:202-203`, `event_bus.py:29-33`, `execution_engine.py:72-84`  
**违反:** CONSTITUTION Article 1 — "The Kernel must be stateless. All state must be written to the Data Plane as Events."

**证据:**
- `cli.py:202` — `bus = EventBus()` 使用无 DB 路径的构造; 所有事件仅存在于内存列表
- `event_bus.py:31` — `self._events: list[Event]` 是纯内存列表; SQLite 写入仅在使用 `db_path` 参数时启用, 但 `cli.py` 未传入
- `execution_engine.py:72` — `outputs: dict[str, Any]` 为运行时的扁平字典, 未写入任何 Event Store
- `execution_engine.py:83-84` — `running` 字典和 `completed_or_failed` 集合均为纯内存状态

**影响:** 内核在重启后完全丢失所有状态. 无法实现 RFC-0102 §10 定义的状态恢复 (stateless recovery). 无法水平伸缩.

---

### S1-2 [A1] 两个事件总线实现并存, backbone/store.py 全部未连线

**文件:** `backbone/bus.py:1-114`, `backbone/event.py:1-60`, `backbone/store.py:1-162`, `backbone/schema.py:1-69`  
**违反:** CONSTITUTION Article 1 — 所有状态需写入 Data Plane; 但完整实现 (backbone/*) 完全未使用

**证据:**
- `backbone/store.py` 实现了符合 RFC-0500 §6 的 EventStore: 追加写入 + 快照 + 重放 API, 但全仓库零引用
- `backbone/bus.py` 实现了符合 RFC-0500 §5 的 EventBus: 死信队列 + at-least-once 递送, 但全仓库零引用
- `backbone/schema.py` 实现了符合 RFC-0500 §7 的 SchemaRegistry, 但全仓库零引用
- P1 使用 `event_bus.py` 中的独立实现, 具有完全不同的 API (无死信, 无 schema 验证, 无 at-least-once 保证)

**影响:** 276 行基础架构代码被浪费 (backbone/* 共 405 行, 其中 P1 实际只调用了 event_bus.py 的一小部分). Event Store 的缺失使内核无法实际成为无状态.

---

### S1-3 [A2] 执行引擎的 TaskExecutor 绕过了 Capability Pool

**文件:** `cli.py:212-216`, `execution_engine.py:110`  
**违反:** CONSTITUTION Article 2 — "No module other than the Execution Engine may dispatch a Task. Capabilities must never call other Capabilities."

**证据:**
- `execution_engine.py:110` — `output = self.executor.execute(task, {**ctx, **outputs})` 引擎直接同步调用 executor, 不是通过 Capability Pool
- `cli.py:212-216` — `engine.executor.register("search", _exec_search)` — executor 注册表在 cli.py 中配置, 直接注册 Python callable
- RFC-0200 §5 要求通过 Capability Pool 进行调用, 但 P1 没有任何 Capability Pool 抽象

**影响:** 每个 Task 调用不可观测, 无法审计, 无法管控并发. 违反了 "every action is observable, auditable, and governable from a single point" 的设计原则.

---

### S1-4 [A4] 跨模块通信绕过 Event Backbone

**文件:** `cli.py:209,261`, `execution_engine.py:51-53,110`  
**违反:** CONSTITUTION Article 4 — "No module may directly call another module's method. All communication must be published as Events on the Event Bus."

**证据:**
- `cli.py:209` — `engine = ExecutionEngine(bus=bus)` — CLI 直接创建 Engine 实例
- `cli.py:261` — `verdict = do_review(exec_result, bus=bus)` — CLI 直接调用 Reviewer
- `execution_engine.py:53` — `self.executor = TaskExecutor()` — Engine 持有 TaskExecutor 的直接引用
- `execution_engine.py:110` — 同步调用 `self.executor.execute()`, 不是通过 Event Bus 的事件驱动
- `cli.py:38-47` — `_exec_llm()` 直接调用 `call_llm()` (from llm_executor), 完全是同步函数调用

**影响:** 违反了 Event Sourcing 的核心原则 (ADR-0001). Event Store 不再是单一真相源, 因为大量通信逻辑发生在 Event Bus 外部.

---

### S1-5 [A7] Capability 包含业务逻辑

**文件:** `cli.py:32-73`  
**违反:** CONSTITUTION Article 7 — "A Capability provides a functional unit. It must never contain business process logic."

**证据:**
- `_exec_search` (第 32-35 行) — 返回硬编码的模拟搜索结果 (Contain business logic about what result format to return)
- `_exec_review` (第 50-58 行) — 聚合 upstream 输出, 执行非空检查 — 这是 Reviewer 的业务逻辑, 不是 Capability 的功能
- `_exec_report` (第 61-73 行) — 按节编译报告 — 这是 Reporter 的业务逻辑, 不是 Capability 的功能
- `_exec_llm` (第 38-47 行) — 在 API 失败时返回硬编码的中文模拟数据 (包含业务决策: 何时使用 mock)

**影响:** 责任边界模糊. Capability 和 Workflow/Rule 的职责分离没有体现.

---

## 🟠 S2 — 规范偏离 (RFC Specification Deviations)

### S2-1 [RFC-0001] 状态机仅实现 4 个状态, 规范要求 17 个状态 + 30+ 个转换

**文件:** `models.py:76`, `execution_engine.py:99-127`  
**违反:** RFC-0001 §3 — "Every Task in Agent OS exists in exactly one of the following states..."

**缺失的状态:**
| 规范状态 | P1 状态 | 缺失影响 |
|-----------|----------|----------|
| `Created` | 无 | 无实例化环节 |
| `Queued` | 无 | 无调度队列 |
| `Assigned` | 无 | 无 Capability 分配 |
| `WaitingReview` | 无 | 无 Review 内省 |
| `Reviewed` | 无 | 无约束评估 |
| `ReviewFailed` | 无 | 无质量门 |
| `RetryQueued` | 无 | 无重试机制 |
| `ReplanRequested` | 无 | 无重新规划 |
| `CancelQueued` / `Cancelled` | 无 | 无取消路径 |
| `Skipped` | 无 | 无条件跳过 |
| `CompletedWithWarning` | `completed` | 警告丢失 |
| `Partial` | 无 | 无部分结果 |
| `Archived` | 无 | 无审计痕迹 |
| `PendingReview` / `PendingQueued` | 无 | 无依赖阻塞 |

**证据:**
- `models.py:76` — `status: str` 的合法值仅 `"pending"`, `"running"`, `"completed"`, `"failed"` (硬编码在 execution_engine.py:99,111,120)
- `execution_engine.py:99-127` — 完整的执行循环只有 try/except, 无状态机驱动

---

### S2-2 [RFC-0001] 无重试机制 — retry 字段已定义但从未使用

**文件:** `models.py:55-56`, `execution_engine.py:108-127`  
**违反:** RFC-0001 §4.2 — "Every Task declares a retry policy"

**证据:**
- `models.py:55-56` — `PlannedTask.retry_count = 0` 和 `max_retries = 3` 已定义, 但 `execution_engine.py` 中完全没有重试循环
- `execution_engine.py:119-127` — 所有异常直接标记为 `failed`, 无重试决策
- RFC-0001 §4.2 要求的 `backoff`, `initial_delay_ms`, `max_delay_ms`, `retryable_errors` 均未实现

**影响:** 临时性失败无法自动恢复. 非致命 API 超时等故障会导致整个工作流失败.

---

### S2-3 [RFC-0200] 无 Capability Contract — 缺少 Core Invocation Interface

**文件:** `llm_executor.py:39-108`, `cli.py:32-73`  
**违反:** RFC-0200 §4.1 — "Every Capability exposes exactly one execution method"

**证据:**
- RFC-0200 §4.1 定义 `Capability.execute(input, context, config) → ExecutionResult`, 但 P1 的 executor 是松散的自由函数
- 输出不符合 RFC-0200 §4.3: 缺少 `status`, `metrics`, `confidence` 字段
- 无错误分类 (RFC-0200 §4.7): 10 个错误代码均未实现
- 无取消接口 (RFC-0200 §4.8): 运行时无法终止正在运行的 Capability
- 无流式输出支持 (RFC-0200 §4.5)
- 无成本追踪报告 (RFC-0200 §8.1)
- `capability_binding` 在 `PlannedTask` 字段但 schema 中的 `requirements` 块完全缺失
- `schemas/capability/` 目录为空 — 无 Capability Manifest schema

**影响:** 任何第三方 Capability 作者无法为其编写兼容实现.

---

### S2-4 [RFC-0500] Event Backbone 仅实现了 pub/sub 的内核, 缺乏关键功能

**文件:** `event_bus.py:39-78`, `event_bus.py:98-113`  
**违反:** RFC-0500 §5.1, §5.2, §7.2

**证据:**
- 无 at-least-once 递送: `event_bus.py:publish()` 是 fire-and-forget, 没有 ack/nack 协议 (RFC-0500 §5.1)
- 无死信队列: `event_bus.py:126` 的 `_safe_call` 静默吞下所有异常 (RFC-0500 §5.4)
- 无 Schema Registry 验证: 创建 Event 时不需要注册 schema (RFC-0500 §7.2)
- 无有序递送保证: 尽管 `events` 列表是有序的, 但订阅者接收通知时没有顺序保证
- `event_bus.py` 的 SQLite 存储 schema 与 `backbone/store.py` 不同且不兼容
- Event 模型冲突: `models.Event` (扁平字段) vs `backbone/event.py:Event` (嵌套 RFC-0500 兼容)
- 发布的事件类型不符合 RFC-0001 §6 的命名约定: `task.started` 应为 `Task:Running`, `task.completed` 应为 `Task:Completed`

---

### S2-5 [RFC-0101] Planner 仅实现简化版本, 缺少 8-Pass Pipeline

**文件:** `planner.py:26-102`  
**违反:** RFC-0101 §3 — "The Planner compiles a Workflow into an Execution Plan through a sequence of passes"

**缺失的 Pass:**
| Pass | 规范定义 | P1 状态 |
|------|----------|---------|
| Pass 1: Parsing | 完整的 YAML 验证 + schema 检查 | 基础实现 |
| Pass 2: Graph Build | 前后向邻接表 + 拓扑排序 | 基础实现 |
| Pass 3: Rule Injection | Rule Manager 注入约束 | 简化: 仅有 `max_tasks` 和 `timeout_seconds` 两个规则 |
| Pass 4: Condition Simplification | 条件评估 + 剪枝传播 | **完全缺失** |
| Pass 5: Dead Node Elimination | 剪枝已删除的节点 | **完全缺失** |
| Pass 6: Capability Bind | Registry 的能力协商 | **完全缺失** — `workflow.capabilities.get(t.type, "default")` 是简单 dict 查找 |
| Pass 7: Cost Optimization | 成本估算 | **完全缺失** |
| Pass 8: Output Format | 标准 Plan 序列化 | **plan 不符合 plan.json schema** |

---

### S2-6 [RFC-0102] Execution Engine 缺少内部模块划分

**文件:** `execution_engine.py:48-161`  
**违反:** RFC-0102 §3 — Engine 应有 7 个内部模块

**缺失的组件:**
| 组件 | 规范定义 | P1 状态 |
|------|----------|---------|
| PlanIngestor | 接收 Plan, 验证, 初始化 | 缺失 — `execute()` 直接处理 Plan |
| TaskFactory | Plan stages → Tasks | 缺失 — `execute()` 直接遍历 `plan.tasks` |
| DependencyTracker | 依赖图 + ready 信号 | 简化 — `in_degree` 字典直连 (无事件驱动) |
| Scheduler | 优先级队列 + Capability Pool 调用 | 缺失 — 直接 `self.executor.execute()` |
| ContextManager | stage 输出结构化积累 | 简化 — `outputs: dict[str, Any]` (无 schema, 无 merge 规则) |
| LifecycleManager | 执行状态机驱动 | 缺失 — 只有线性进度 |
| EventPublisher | 所有状态转换发布 | 基础 — 仅发布 `task.started/completed/failed` |

---

### S2-7 [RFC-0102] 无能力池调用 — 直接调用 Executor

**文件:** `execution_engine.py:110`  
**违反:** RFC-0102 §4.5, RFC-0200 §5

**规范路线:**
```
Scheduler → CapabilityPool.invoke(task) → capability_instance.execute()
             ↓ 返回 Capability:OutputProduced/Error 事件
```

**P1 路线:**
```
self.executor.execute(task, {**ctx, **outputs})  # 直接同步函数调用
```

**影响:** 无并发控制, 无健康检查, 无实例管理, 无视能力池的生命周期.

---

### S2-8 [RFC-0102] 无状态恢复实现

**文件:** `execution_engine.py:48-161`, `backbone/store.py`  
**违反:** RFC-0102 §10 — "Engine State Recovery (Stateless Kernel)"

**证据:**
- 尽管 `backbone/store.py` 实现了恢复所需的基础设施 (Replay API, snapshot), 但从未与 Engine 集成
- `execution_engine.py` 没有任何恢复入口点或重放逻辑
- RFC-0102 §10.2 定义的 6 步恢复流程完全未实现

---

### S2-9 Plan 输出不符合 plan.json Schema

**文件:** `models.py:61-67`, `schemas/execution/plan.json`  
**违反:** `schemas/execution/plan.json` 定义了兼容性要求的 Plan 格式

**缺失/不符合的字段:**
| Schema 要求 | P1 Plan | 差距 |
|-------------|---------|------|
| `plan_id` (必需) | 无 | **缺失** |
| `workflow_ref` (必需, pattern `wf://`) | `workflow_id: str` | 格式不匹配 |
| `execution_id` (必需, pattern `exec://`) | 无 | **缺失** |
| `compiled_at` (必需, ISO 8601) | `created_at: datetime` | 命名不匹配 |
| `stages[].requirements` (必需) | 无 | **缺失** |
| `stages[].capability_binding.capability_id` | `capability: str = "default"` | 仅为字符串, 非结构化对象 |
| `pruning_log` | 无 | **缺失** |
| `profile_ref` | 无 | **缺失** |
| `stages[].optimization_hints` | 无 | **缺失** |
| `stages[].replan_allowed` | 无 | **缺失** |
| `stages[].condition` | 无 | **缺失** |

---

### S2-10 架构空目录 — `schemas/` 中能力与事件 schema 缺失

**文件:** `schemas/capability/` (空), `schemas/event/` (空)  
**违反:** RFC-0200 (需要 Capability Manifest schema), RFC-0500 §7 (需要 Event schema 注册)

**证据:**
- `schemas/capability/` 是空文件夹 — 缺少 Capability Manifest JSON Schema (RFC-0201)
- `schemas/event/` 是空文件夹 — 没有为 RFC-0001 §6 定义的 25+ 事件类型注册 schema
- `task_executors/__init__.py` 仅包含 docstring, 无实际实现

---

## 🔵 S3 — 代码质量 (Code Quality Issues)

### S3-1 276 行死背代码 — backbone/* 全部未使用

**文件:** `backbone/bus.py` (114 行), `backbone/event.py` (60 行), `backbone/store.py` (162 行)  
**严重性:** 中等

这些文件实现了规范的 RFC-0500 Event Backbone (总线 + 死信队列 + Schema 注册 + Event Store), 但 P1 模块全部使用 `event_bus.py` 中的简化实现. 通过 `search_files` 验证: `from .backbone` 或 `import backbone` 在全仓库中零出现.

---

### S3-2 两个冲突的 Event 模型

**文件:** `models.py:114-121` vs `backbone/event.py:10-61`  
**严重性:** 中等

| `models.Event` | `backbone/event.py:Event` |
|----------------|--------------------------|
| 扁平字段: `id`, `type`, `source`, `data`, `timestamp` | 嵌套结构: `event_id`, `event_type`, `version`, `source` (dict), `payload` (dict), `metadata` (dict), `context` (dict) |
| RFC-0001 §6 的扁平适配 | RFC-0500 §4 的规范适配 |
| P1 所有模块使用 | 全仓库零引用 |

两者不可互换. 选择一种模型并移除另一种.

---

### S3-3 cli.py 是 5 个关注点混在一个文件

**文件:** `cli.py` (438 行)  
**严重性:** 中等

1. **CLI 解析** (第 98-135 行) — argparse 设置
2. **Executor 实现** (第 32-93 行) — 搜索/LLM/审查/报告的 Capability 实现
3. **工作流编排** (第 191-311 行) — 加载 → 规划 → 执行 → 审查 → 报告的完整流程
4. **报告格式化** (第 266-311 行) — JSON 报告生成
5. **工作流验证** (第 314-435 行) — YAML 验证逻辑

应拆分为: `cli.py` (仅 CLI), `executors/search.py`, `executors/llm.py`, `executors/review.py`, `executors/report.py`.

---

### S3-4 生产代码中的模拟/硬编码数据

**文件:** `cli.py:35,47`  
**严重性:** 低

```python
# cli.py:35
return "【搜索结果】\n查询: {query}...（注：v1 原型使用模拟数据）"
# cli.py:47
return "【LLM 分析结果 — API不可用，使用模拟数据】\n\n## 投资亮点..."
```

模拟数据与生产逻辑混在一起. 用户可能在没有 API 密钥的情况下运行并获得虚假结果.

---

### S3-5 异常吞没

**文件:** `event_bus.py:124-126`, `event_bus.py:112-113`, `backbone/store.py:154`  
**严重性:** 中等

```python
# event_bus.py:124-126 — 所有 handler 异常被静默吞没
except Exception:
    logger.exception("Event handler %s failed on %s", handler, event)

# event_bus.py:112-113 — 重复事件 ID 静默忽略
except sqlite3.IntegrityError:
    pass  # duplicate event id

# backbone/store.py:154 — 表可能不存在的错误静默忽略
except sqlite3.OperationalError:
    pass  # table might not exist yet
```

`Exception` 的静默吞没隐藏了可能导致系统行为错误的订阅者失败.

---

### S3-6 高耦合 — ExecutionEngine 直接创建 TaskExecutor

**文件:** `execution_engine.py:53`  
**严重性:** 低

```python
self.executor = TaskExecutor()
```

Engine 和 TaskExecutor 是硬编码的组合, 而非依赖注入. 这使得测试替代 executor 或在测试中 mock 变得困难.

---

### S3-7 死代码字段 — PlannedTask 的 retry 字段未使用

**文件:** `models.py:55-57`, `execution_engine.py:108-127`  
**严重性:** 低

```python
# models.py:55-57
retry_count: int = 0
max_retries: int = 3
timeout: int = 120
```

这些字段在 `PlannedTask` 中定义, 但在 `execution_engine.py` 中从未读取或使用. 执行循环是无重试的线性遍历.

---

### S3-8 没有测试文件

**文件:** 项目范围  
**严重性:** 高

仓库中没有测试目录 (`tests/`, `testsuite/`, `test_*.py`). 1784 行 Python 代码没有任何自动化测试.

---

### S3-9 事件类型命名不符合 RFC 约定

**文件:** `execution_engine.py:104,116,125,147`, `planner.py:93`, `workflow_loader.py:121`  
**严重性:** 低

P1 使用 `"task.started"`, `"task.completed"`, `"task.failed"`, `"execution.finished"`, `"plan.ready"`, `"workflow.loaded"` 作为事件类型名称.

RFC-0001 §6 和 RFC-0500 §7.4 要求: `"Task:Running"`, `"Task:Completed"`, `"Task:Failed"`, `"Execution:Running"`, `"Plan:Ready"`, `"Workflow:Loaded"`.

---

## 📊 汇总

| 严重性 | 数量 | 关键文件 |
|--------|------|----------|
| **S1** — 架构违规 | 5 | `cli.py`, `execution_engine.py`, `event_bus.py`, `backbone/*` |
| **S2** — 规范偏离 | 10 | `models.py`, `planner.py`, `execution_engine.py`, `cli.py`, `schemas/execution/plan.json`, `llm_executor.py` |
| **S3** — 代码质量 | 9 | `backbone/*`, `cli.py`, `event_bus.py`, `models.py` |
| **总计** | **24** | — |

**主要发现:**
1. **两个并行的事件基础设施** — `event_bus.py` (P1 使用) 和 `backbone/*` (规范兼容但未连线) 是最大的架构问题, 占 ~680 行未连线的规范兼容代码
2. **状态机基本不存在** — 4 个状态 vs 规范要求的 17 个状态
3. **无 Capability Contract** — 直接函数调用替换了 Capability Pool 架构
4. **无测试覆盖** — 1784 行代码零测试
5. **无 Engine 状态恢复** — 违反 Constitution Article 1 的核心理念
