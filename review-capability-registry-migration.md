# Capability/Workflow 注册方式 → Registry 迁移审查报告

## 一、现状分析

### 当前注册链路

```
workflows/*.yaml                    (workflow definition)
    ↓ 引用 type 字段
capabilities/__init__.py            (硬编码 dict)
    ↓ 遍历 CAPABILITIES.items()
cli.py: _cmd_run()                  (注册点)
    ↓ engine.pool.register(tp, fn)
capability_pool.py: CapabilityPool  (内部 _registry dict)
    ↓ invoke(task, context)
```

### 涉及文件一览

| 文件 | 角色 | 问题 |
|------|------|------|
| `capabilities/__init__.py` | 类型→函数 的硬编码字典 | 所有注册逻辑耦合于此，无法扩展、无法查询 |
| `capabilities/search.py` | 函数 `(PlannedTask, dict) → str` | 无 schema/元信息，签名隐式约定 |
| `capabilities/llm.py` | 函数 `(PlannedTask, dict) → str` | 同上 |
| `capabilities/review.py` | 函数 `(PlannedTask, dict) → dict` | 同上（返回类型不同） |
| `capabilities/report.py` | 函数 `(PlannedTask, dict) → str` | 同上 |
| `cli.py` (L147-149) | 导入 dict 并逐项 register | 硬编码导入，注册逻辑泄漏到 CLI |
| `capability_pool.py` | 持有 `_registry: dict[str, Callable]` | 零元信息、零发现、无生命周期 |
| `planner.py` (L63) | 读取 `workflow.capabilities` | 该字段只在 planner 中传递，实际上无消费方 |
| `task_executors/__init__.py` | 空文件 | 冗余目录，与 `capabilities/` 职责重叠 |
| `workflow_loader.py` (L116) | 解析 YAML 中 `capabilities` 字段 | 解析后未与任何注册机制联动 |
| `models.py` (L157) | `Workflow.capabilities` 字段 | 定义存在，实际未被注册流程使用 |

---

## 二、需要改动的文件及接口

### 修改优先级分层

```
P0 — 核心接口和数据流（不改则无法迁移）
P1 — 注册发现与元信息（Registry 的核心价值）
P2 — 清理与新能力（解耦、插件化、装饰器）
```

---

### P0: 必须改动（核心注册链路）

#### 1. 新增 `capability_registry.py` — 核心 Registry

**接口定义：**

```python
@dataclass
class CapabilityMeta:
    """Capability 元信息"""
    name: str                       # 唯一标识（如 "search"）
    description: str                # 描述
    fn: Callable[[PlannedTask, dict], Any]  # 执行函数
    aliases: list[str] = field(default_factory=list)  # 别名（如 "gather" → "review"）
    input_schema: dict | None = None   # 期望 params schema (JSON Schema)
    output_type: str = "str"           # 输出类型描述
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)

class CapabilityRegistry:
    def __init__(self):
        self._capabilities: dict[str, CapabilityMeta] = {}  # name → meta
        self._alias_map: dict[str, str] = {}                # alias → canonical name

    def register(self, meta: CapabilityMeta) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> CapabilityMeta | None: ...
    def list(self) -> list[CapabilityMeta]: ...
    def get_callable(self, name: str) -> Callable | None: ...
    def resolve(self, name: str) -> str: ...  # 别名解析
    def has_type(self, task_type: str) -> bool: ...
```

#### 2. `capability_pool.py` — 改用 Registry

**改动点：**
- `CapabilityPool.__init__` 接受 `CapabilityRegistry` 而非裸 dict
- `CapabilityPool.register` 委托给 `registry.register(CapabilityMeta(...))`
- `CapabilityPool.invoke` 通过 `self._registry.get_callable(task.type)` 获取函数
- 新增 `CapabilityPool.list_capabilities()` 暴露注册元信息

```python
# 当前
class CapabilityPool:
    def __init__(self):
        self._registry: dict[str, Callable] = {}

# 改为
class CapabilityPool:
    def __init__(self, registry: CapabilityRegistry | None = None):
        self._registry = registry or CapabilityRegistry()
```

#### 3. `capabilities/__init__.py` — 改为 Registry 注册调用

**当前：** 硬编码 `CAPABILITIES` dict
**改为：** 提供 `register_all(registry: CapabilityRegistry)` 函数，逐个调用

```python
from .capability_registry import CapabilityRegistry, CapabilityMeta
from .search import search
from .llm import llm
from .review import review
from .report import report

def register_all(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityMeta(
        name="search", fn=search,
        description="Execute a web search query",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_type="str",
    ))
    registry.register(CapabilityMeta(
        name="llm", fn=llm,
        description="Call an LLM for analysis",
        input_schema={"type": "object", "properties": {"prompt": {"type": "string"}}},
        output_type="str",
    ))
    registry.register(CapabilityMeta(
        name="review", fn=review, aliases=["gather"],
        description="Review and aggregate previous outputs",
        output_type="dict",
    ))
    registry.register(CapabilityMeta(
        name="report", fn=report,
        description="Compile final report output",
        output_type="str",
    ))
```

#### 4. `cli.py` — 解耦注册逻辑

**当前 (L21, L147-149)：**
```python
from .capabilities import CAPABILITIES
...
for tp, fn in CAPABILITIES.items():
    engine.pool.register(tp, fn)
```

**改为：**
```python
from .capabilities import register_all
...
register_all(engine.pool.registry)  # 或 engine.pool.register_all()
```

或更优方案——由 `ExecutionEngine` 自行注册：

```python
# cli.py
engine = ExecutionEngine(bus=bus)
# 新增：engine bootstrap 时自动注册 built-in capabilities
```

#### 5. `execution_engine.py` — 初始化时携带 Registry

**当前 (L48)：**
```python
self.pool = CapabilityPool()
```

**改为：**
```python
from .capabilities import register_all

class ExecutionEngine:
    def __init__(self, bus=None, registry=None):
        self.bus = bus
        self.pool = CapabilityPool(registry or self._build_default_registry())

    @staticmethod
    def _build_default_registry() -> CapabilityRegistry:
        from .capability_registry import CapabilityRegistry
        reg = CapabilityRegistry()
        register_all(reg)
        return reg
```

---

### P1: 注册发现与元信息（Registry 价值体现）

#### 6. 新增 `CapabilityRegistry.list()` 与 CLI 集成

- `cli.py`: 新增子命令 `capabilities`，支持：
  ```
  agent-os capabilities list          # 列出所有已注册 capability
  agent-os capabilities show <name>   # 查看某个 capability 的元信息
  ```
- `capability_registry.py`: 新增 `list()` 和 `get()` 接口（已在 P0 定义）

#### 7. `workflow_loader.py` — 注册联动校验

**当前：** 解析 YAML 时检查 task 是否有 `type`，但不校验该 type 是否已注册。
**改为：** 解析后校验 `type` 是否在 Registry 中。

```python
def load_from_path(path, bus=None, registry: CapabilityRegistry | None = None):
    ...
    # 新增校验
    if registry:
        for t in tasks:
            if not registry.has_type(t.type):
                raise WorkflowLoadError(
                    f"Task '{t.id}' references unknown capability type '{t.type}'. "
                    f"Available: {registry.list()}"
                )
```

#### 8. `planner.py` — 废弃 unused `workflow.capabilities` 字段

**当前 (L63)：** `capability=workflow.capabilities.get(t.type, "default")`
- `Workflow.capabilities` 字段在 YAML 中解析、在 planner 中读取，但没有任何系统消费这个值
- `CapabilityPool.invoke` 仅按 `task.type` 查找，完全不使用 `PlannedTask.capability` 字段

**改动：**
- 移除 `Workflow.capabilities` 字段（或标记 deprecated 并置 null 默认）
- 移除 `PlannedTask.capability` 字段（或改为从 Registry 反向查询）

---

### P2: 清理与新能力

#### 9. 删除 `task_executors/` 目录

- 该目录下只有空 `__init__.py`，与 `capabilities/` 职责完全重叠
- **动作：** 删除 `task_executors/__init__.py` 和空目录

#### 10. 新增 `@capability` 装饰器（可选，未来增强）

```python
# capability_registry.py 或新文件 capabilities/decorator.py

def capability(name: str, description: str = "", aliases: list[str] | None = None,
               input_schema: dict | None = None, output_type: str = "str",
               version: str = "1.0.0", tags: list[str] | None = None):
    def wrapper(fn):
        fn.__capability_meta__ = {
            "name": name,
            "description": description,
            "aliases": aliases or [],
            "input_schema": input_schema,
            "output_type": output_type,
            "version": version,
            "tags": tags or [],
        }
        return fn
    return wrapper
```

使用方式：

```python
@capability(name="search", description="Execute web search", output_type="str")
def search(task: PlannedTask, context: dict) -> str: ...
```

然后 `register_all()` 可以改为自动扫描 `__capability_meta__`：

```python
def register_all(registry, module=None):
    """Auto-discover @capability-decorated functions in given module."""
    import inspect
    module = module or inspect.getmodule(inspect.stack()[1][0])
    for name, obj in inspect.getmembers(module):
        meta = getattr(obj, "__capability_meta__", None)
        if meta:
            registry.register(CapabilityMeta(fn=obj, **meta))
```

#### 11. 插件化支持（未来扩展）

Registry 直接支持第三方插件注册：

```python
# 用户代码或插件
from agentos.capability_registry import CapabilityRegistry, CapabilityMeta

def register_my_plugin(registry: CapabilityRegistry):
    registry.register(CapabilityMeta(
        name="my_custom_tool",
        fn=my_handler,
        description="...",
        tags=["plugin"],
    ))
```

然后在 CLI 中通过 `--plugin` 或配置自动加载：

```bash
agent-os run my_workflow --plugin my_plugin
```

---

## 三、改动清单汇总

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | **新建** `capability_registry.py` | ✨ Create | `CapabilityMeta` dataclass + `CapabilityRegistry` class |
| 2 | `capability_pool.py` | 🔧 Modify | `CapabilityPool` 接受 Registry 而非裸 dict；新增 `list_capabilities()` |
| 3 | `capabilities/__init__.py` | 🔧 Modify | 从导出 `CAPABILITIES` dict 改为导出 `register_all(registry)` 函数 |
| 4 | `cli.py` | 🔧 Modify | L147-149 改为 `register_all(engine.pool.registry)`；新增子命令 `capabilities` |
| 5 | `execution_engine.py` | 🔧 Modify | `ExecutionEngine.__init__` 可选接受 Registry，或自建默认 Registry |
| 6 | `workflow_loader.py` | 🔧 Modify | 加载时增加 `type` 注册校验；接受可选 `registry` 参数 |
| 7 | `planner.py` | 🔧 Modify | 移除对 `workflow.capabilities` 的依赖 |
| 8 | `models.py` | 🔧 Modify | 标记 `Workflow.capabilities` 为 deprecated（或移除）|
| 9 | `capabilities/search.py` | 🔧 Modify | 可选加 `@capability` 装饰器 |
| 10 | `capabilities/llm.py` | 🔧 Modify | 同上 |
| 11 | `capabilities/review.py` | 🔧 Modify | 同上 |
| 12 | `capabilities/report.py` | 🔧 Modify | 同上 |
| 13 | `task_executors/__init__.py` | 🗑️ Delete | 空目录，与 capabilities/ 重叠 |
| 14 | `task_executors/` 目录 | 🗑️ Delete | 删除空目录 |
| 15 | **新建** `tests/test_capability_registry.py` | ✨ Create | 新增测试 |
| 16 | **可选新建** `capabilities/decorator.py` | ✨ Create | `@capability` 装饰器（P2） |

### 不可改文件（不涉及）

- `backbone/bus.py` — 事件总线不受影响
- `backbone/event.py` — Event 定义不受影响
- `backbone/schema.py` — Event Schema 已有 Registry；Capability Registry 是独立概念
- `backbone/store.py` — Event Store 不受影响
- `llm_executor.py` — LLM HTTP 调用层不受影响
- `reporter.py` — 报告格式化不受影响
- `reviewer.py` — 评审逻辑不受影响

---

## 四、迁移步骤建议

```
Step 1 — 新建 capability_registry.py（P0 核心）
    ↓
Step 2 — 修改 capabilities/__init__.py 为 register_all()
    ↓
Step 3 — 修改 capability_pool.py 接入 Registry
    ↓
Step 4 — 修改 cli.py + execution_engine.py 使用新注册方式
    ↓
Step 5 — 修改 workflow_loader.py 增加注册校验（P1）
    ↓
Step 6 — 清理 task_executors/、标记 deprecated 字段（P2）
    ↓
Step 7 — 新增 tests 和 CLI capabilities 子命令（P1）
    ↓
Step 8 — 新增 @capability 装饰器（P2，可选）
```

---

## 五、风险与注意事项

1. **向后兼容：** `CapabilityPool.register()` 旧签名应保留一个版本周期，或直接内部映射到 Registry
2. **Type alias 统一处理：** 当前 `"gather"` 别名在 `CAPABILITIES` dict 中直接映射；迁移后由 `CapabilityMeta.aliases` 统一管理
3. **测试覆盖：** `CapabilityRegistry` 注册、别名解析、按 type 查询、不存在的 type 处理都需要单元测试
4. **CLI 验收标准：** 迁移完成后 `agent-os run competitor_analysis -q "AI芯片"` 应正常执行；`agent-os capabilities list` 应列出所有注册的 capability
