# RFC-0400: Agent OS Capability SDK

> **让第三方能在 30 分钟内写出第一个 Capability**

| Field | Value |
|-------|-------|
| Status | **Draft** |
| Author | Agent OS Architecture Team |
| Depends On | RFC-0300 (Registry), RFC-0200 (CapabilityPool) |

---

## 1. 问题陈述

当前 Agent OS 的 Capability 只能在 `agentos/capabilities/` 包内以内建方式注册。
第三方开发者需要一个**零摩擦的 SDK**，让他们在 30 分钟内完成：
1. 编写一个外部 Capability
2. 本地验证 manifest + fn 签名
3. 注册到 Agent OS Registry
4. 在 ExecutionEngine 中执行

## 2. 设计原则

1. **最小接口** — 开发者只需写一个 YAML manifest + 一个 Python 函数
2. **约定优于配置** — 固定的目录结构，无需手动注册
3. **提前验证** — manifest schema + fn 签名在注册/加载时完成，不在运行时
4. **渐进增强** — 从 3 个文件开始，高级功能（input_schema 校验、异步、事件）可选
5. **向前兼容** — SDK 不改变 Registry/Pool/Engine 现有接口

## 3. Capability SDK 最小接口

### 3.1 开发者需要写什么？

一个外部 Capability 就是一个包含 3 个文件的 Python 包：

```
my-capability/
├── __init__.py          # 包标记 + 可选导出
├── manifest.yaml        # Capability 元数据
└── handler.py           # 实现函数
```

#### `handler.py` — 核心实现

```python
"""My first external capability."""

def handler(task, context):
    """
    Args:
        task: PlannedTask — 当前任务元数据 (task.id, task.type, task.params)
        context: dict — 已完成任务的输出（按 task_id 索引）

    Returns:
        Any — 输出值，会被注入后续任务的 context
    """
    query = task.params.get("query", "")
    # ... 你的逻辑 ...
    return {"result": f"Hello from {task.type}! Query was: {query}"}
```

**签名约束**（由 SDK 验证）：
- 参数：`(task, context)` 恰好 2 个位置参数
- 返回：任意可序列化的值或 None

#### `manifest.yaml` — 元数据

```yaml
task_type: hello-world
display_name: Hello World Capability
description: A simple greeting capability for demo purposes
version: 0.1.0
tags: [demo, greeting]
source: external
enabled: true
input_schema:
  type: object
  properties:
    query:
      type: string
      description: The query string
output_schema:
  type: object
  properties:
    result:
      type: string
```

#### `__init__.py` — 包标记

```python
"""hello-world capability package."""
# 可选：从 handler 重导出
from .handler import handler

__all__ = ["handler"]
```

### 3.2 与 Registry 的集成点

```
   manifest.yaml  ──load_manifest_from_yaml()──▶  CapabilityManifest
                                                        │
   handler.py    ──import handler ──────────────────▶  manifest.fn = handler
                                                        │
                                                        ▼
                                              Registry.register_manifest()
                                                        │
                                                        ▼
                                              CapabilityPool.invoke()
                                                        │
                                                        ▼
                                              ExecutionEngine.execute()
```

### 3.3 Registry 发现外部 Capability 的两种模式

**模式 A — 目录扫描**（推荐）：

```bash
agentos capability discover --dir ./my-capability/
```

Registry 扫描指定目录，寻找 `manifest.yaml`，通过约定 `handler.py` 发现 fn。

**模式 B — 显式注册**：

```python
from agentos.sdk import load_capability

load_capability("path/to/my-capability")
# 等价于：
# registry.register_manifest("hello-world", manifest)
```

---

## 4. 外部 Capability 目录结构和文件规范

### 4.1 标准布局

```
my-capability/                   # 包目录
├── __init__.py                  # [必须] 空文件或重导出 handler
├── manifest.yaml                # [必须] CapabilityManifest 元数据
├── handler.py                   # [必须] handler(task, context) 函数
├── requirements.txt             # [可选] 额外依赖
├── tests/                       # [推荐] 单元测试
│   └── test_handler.py          # 测试 handler
└── examples/                    # [可选] 使用示例
    └── quickstart.yaml          # 配套的工作流 YAML
```

### 4.2 manifest.yaml 字段定义

| 字段 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task_type` | string | **是** | — | 唯一标识，小写 kebab-case |
| `display_name` | string | 否 | 与 task_type 相同 | 人类可读名称 |
| `description` | string | 否 | "" | 功能描述 |
| `version` | string | 否 | "0.1.0" | SemVer |
| `tags` | list[string] | 否 | [] | 分类标签 |
| `source` | string | 否 | "external" | 来源标记 |
| `enabled` | bool | 否 | true | 是否启用 |
| `input_schema` | dict | 否 | null | JSON Schema |
| `output_schema` | dict | 否 | null | JSON Schema |
| `entry_point` | string | 否 | "handler.handler" | 函数引用路径（包内） |

> `entry_point` 字段：当 handler 函数不在 `handler.py` 的默认位置时，使用 `"module.attr"` 格式指定。

### 4.3 函数签名规范

```python
def handler(task, context) -> Any:
    """External capability implementation.

    Positional arguments (exactly 2):
        task:      PlannedTask  (has .id, .type, .params dict)
        context:   dict[str, Any] (已完成任务的输出，key=task_id)

    Returns:
        Any serializable value — injected into downstream task contexts.
    """
```

验证规则（由 `validate()` 执行）：
- `callable(fn)` 为 True
- `fn` 恰好接受 2 个位置参数（不强制参数名）
- 函数体可执行（语法正确）

---

## 5. `agentos capability scaffold` 命令

### 5.1 用法

```bash
# 生成默认名称的 capability
agentos capability scaffold hello-world
# 输出到当前目录下的 ./hello-world/

# 指定输出路径
agentos capability scaffold hello-world --output ./custom/path/

# 指定版本和标签
agentos capability scaffold hello-world --version 0.1.0 --tags demo,greeting

# 使用 JSON schema 模板
agentos capability scaffold hello-world --with-schema
```

### 5.2 生成的模板代码

运行 `agentos capability scaffold hello-world` 生成：

```
hello-world/
├── __init__.py
├── manifest.yaml
├── handler.py
├── requirements.txt
├── tests/
│   └── test_handler.py
└── examples/
    └── hello-world-workflow.yaml
```

#### `manifest.yaml`

```yaml
task_type: hello-world
display_name: Hello World
description: A capability scaffolded by Agent OS SDK
version: 0.1.0
tags: [demo]
source: external
enabled: true
entry_point: handler.handler
# input_schema:
#   type: object
#   properties:
#     query:
#       type: string
# output_schema:
#   type: object
#   properties: {}
```

#### `handler.py`

```python
"""hello-world capability — Agent OS SDK scaffold."""
from __future__ import annotations
from typing import Any


def handler(task, context) -> Any:
    """Execute the hello-world capability.

    Args:
        task: PlannedTask — current task metadata (id, type, params).
        context: dict — outputs from completed tasks, keyed by task_id.

    Returns:
        Any — result to inject into downstream task contexts.
    """
    _ = context  # available for cross-task data access
    query = task.params.get("query", "")
    # TODO: implement your capability logic here
    return {"result": f"hello-world processed: {query}"}
```

#### `tests/test_handler.py`

```python
"""Tests for the hello-world capability."""
from hello_world.handler import handler
from unittest.mock import MagicMock


def test_handler_returns_result():
    task = MagicMock()
    task.id = "t1"
    task.type = "hello-world"
    task.params = {"query": "test"}
    context = {}

    result = handler(task, context)
    assert result is not None
    assert "result" in result
```

#### `examples/hello-world-workflow.yaml`

```yaml
id: hello-world-demo
name: Hello World Demo
description: A simple workflow using the hello-world capability
tasks:
  - id: greet
    type: hello-world
    params:
      query: "Agent OS"
    enabled: true
```

### 5.3 生成逻辑伪代码

```
function scaffold(name, output_dir, options):
    dir = output_dir / name
    create_directory(dir)
    create_directory(dir / "tests")
    create_directory(dir / "examples")

    write(dir / "__init__.py", template___init__py(name))
    write(dir / "manifest.yaml", template_manifest(name, options))
    write(dir / "handler.py", template_handler(name))
    write(dir / "requirements.txt", "")
    write(dir / "tests/test_handler.py", template_test(name))
    write(dir / "examples/{name}-workflow.yaml", template_workflow(name))

    printf("✅ Capability '{name}' scaffolded at: {dir}")
```

---

## 6. 外部 Capability 如何被 Registry 发现并加载

### 6.1 发现流程

```
discover(path)
    │
    ├──▶ 扫描 path 下所有子目录
    │     匹配条件：目录包含 manifest.yaml
    │
    ├──▶ 对每个匹配的目录：
    │     ├── 1. load_manifest_from_yaml("manifest.yaml")
    │     ├── 2. 解析 entry_point (默认 "handler.handler")
    │     ├── 3. 动态 import 模块 → getattr(module, attr_name)
    │     ├── 4. 将 fn 注入 manifest.fn = imported_fn
    │     ├── 5. validate_manifest(manifest) ← schema + fn 签名
    │     └── 6. registry.register_manifest(manifest.task_type, manifest)
    │
    └──▶ 返回 [CapabilityManifest, ...] 注册成功的列表
```

### 6.2 发现算法

```python
def discover(
    path: str | Path,
    registry: Registry | None = None,
) -> list[CapabilityManifest]:
    """Discover external capabilities in a directory tree.

    For each subdirectory containing a manifest.yaml:
        1. Load the manifest from YAML
        2. Import the handler function via entry_point
        3. Inject fn into manifest
        4. Validate manifest + fn signature
        5. Register with registry (if provided)
    """
    path = Path(path)
    manifests: list[CapabilityManifest] = []
    errors: list[dict] = []

    for entry_dir in sorted(path.iterdir()):
        if not entry_dir.is_dir():
            continue
        manifest_path = entry_dir / "manifest.yaml"
        if not manifest_path.exists():
            continue

        try:
            manifest = load_manifest_from_yaml(manifest_path)

            # Resolve entry_point
            ep = manifest.entry_point or "handler.handler"
            module_path, attr_name = ep.rsplit(".", 1)

            # Dynamic import — must be a resolvable Python import
            handler_mod = __import__(
                f"{entry_dir.name}.{module_path}",
                fromlist=[attr_name]
            )
            # For relative imports, use importlib
            # ...

            fn = getattr(handler_mod, attr_name)
            manifest.fn = fn

            # Validate
            validate_capability(manifest)

            # Register
            if registry:
                registry.register_manifest(manifest.task_type, manifest)

            manifests.append(manifest)
        except Exception as e:
            errors.append({"dir": str(entry_dir), "error": str(e)})

    return manifests
```

### 6.3 安装式发现

第三方 Capability 打包为 pip 包后：

```python
# 安装：pip install agentos-capability-hello-world
# 代码中使用 entry_points 机制发现
from importlib.metadata import entry_points

def discover_installed_packages(registry: Registry) -> list[CapabilityManifest]:
    """Discover capabilities installed as pip packages."""
    discovered = entry_points(group="agentos.capabilities")
    manifests = []
    for ep in discovered:
        try:
            loader = ep.load()  # 返回一个 load() 函数
            manifest = loader()  # 返回 CapabilityManifest
            registry.register_manifest(manifest.task_type, manifest)
            manifests.append(manifest)
        except Exception as e:
            logger.error("Failed to load %s: %s", ep.name, e)
    return manifests
```

对应的第三方包 `setup.py` 声明：

```python
entry_points={
    "agentos.capabilities": [
        "hello-world = hello_world:load_manifest",
    ],
}
```

---

## 7. 验证机制

### 7.1 Manifest 验证

```python
def validate_manifest(manifest: CapabilityManifest) -> list[str]:
    """Validate a CapabilityManifest. Returns list of error messages."""
    errors: list[str] = []

    if not manifest.task_type:
        errors.append("task_type is required")

    if not re.match(r'^[a-z][a-z0-9-]{1,63}$', manifest.task_type):
        errors.append("task_type must be lowercase kebab-case, 2-64 chars")

    if not manifest.entry_point:
        errors.append("entry_point is required for external capabilities")

    if not manifest.fn:
        errors.append("fn (handler function) is required")

    if manifest.input_schema:
        try:
            validate_json_schema(manifest.input_schema)  # jsonschema 库
        except Exception as e:
            errors.append(f"input_schema is invalid JSON Schema: {e}")

    # ... similar for output_schema

    return errors
```

### 7.2 Fn 签名验证

```python
import inspect

def validate_fn_signature(fn: Callable) -> list[str]:
    """Validate handler function signature."""
    errors: list[str] = []

    if not callable(fn):
        errors.append("handler must be a callable")
        return errors

    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError) as e:
        errors.append(f"cannot inspect handler signature: {e}")
        return errors

    params = list(sig.parameters.values())
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]

    if len(positional) < 2:
        errors.append(f"handler must accept exactly 2 positional arguments "
                      f"(task, context), got {len(positional)}")
    if len(positional) > 2:
        errors.append(f"handler accepts {len(positional)} positional arguments, "
                      f"expected 2 (task, context)")

    # Return annotation — informative only
    return_annotation = sig.return_annotation
    if return_annotation is inspect.Parameter.empty:
        pass  # No return annotation is fine
    elif return_annotation is not None:
        pass  # Any return type is acceptable

    return errors
```

### 7.3 完整验证入口

```python
def validate_capability(manifest: CapabilityManifest) -> dict:
    """Full validation of a capability. Returns {valid: bool, errors: [...], warnings: [...]}."""
    errors = []
    warnings = []

    errors.extend(validate_manifest(manifest))
    errors.extend(validate_fn_signature(manifest.fn))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
```

---

## 8. 新文件清单和改动范围

### 8.1 新增文件

| # | 文件路径 | 说明 | 预估行数 |
|---|----------|------|---------|
| 1 | `src/agentos/sdk/__init__.py` | SDK 包入口，导出公共 API | 20 |
| 2 | `src/agentos/sdk/loader.py` | 外部 Capability 发现 + 加载 (discover, load_capability) | 120 |
| 3 | `src/agentos/sdk/validator.py` | Manifest schema 验证 + fn 签名验证 | 100 |
| 4 | `src/agentos/sdk/scaffold.py` | `agentos capability scaffold` 命令实现 + 模板 | 150 |
| 5 | `src/agentos/sdk/templates/` | Jinja2 或 f-string 模板目录 | — |
| 6 | `src/agentos/sdk/templates/handler.py.j2` | handler.py 模板 | 20 |
| 7 | `src/agentos/sdk/templates/manifest.yaml.j2` | manifest.yaml 模板 | 16 |
| 8 | `src/agentos/sdk/templates/__init__.py.j2` | `__init__.py` 模板 | 5 |
| 9 | `src/agentos/sdk/templates/test_handler.py.j2` | 测试模板 | 20 |
| 10 | `src/agentos/sdk/templates/workflow.yaml.j2` | 工作流示例模板 | 12 |
| 11 | `tests/test_sdk_loader.py` | Loader 单元测试 | 80 |
| 12 | `tests/test_sdk_validator.py` | Validator 单元测试 | 80 |
| 13 | `tests/test_sdk_scaffold.py` | Scaffold 单元测试 | 60 |
| 14 | `tests/test_sdk_integration.py` | 集成测试：scaffold → discover → register → execute | 80 |
| 15 | `examples/external-capabilities/hello-world/` | 完整外部 Capability 示例 | ~6 files |

### 8.2 改动文件

| # | 文件路径 | 改动内容 | 改动量 |
|---|----------|---------|--------|
| 1 | `src/agentos/cli.py` | 新增 `capability` 子命令组 (scaffold, discover, validate) | +80 行 |
| 2 | `src/agentos/registry/__init__.py` | 新增 `Registry.discover_external()` 方法 | +20 行 |
| 3 | `src/agentos/registry/manifest.py` | Manifest 新增 `entry_point` 字段 | +1 行 |
| 4 | `pyproject.toml` | SDK 可选依赖 `agentos[sdk]` 或 `agentos[capability-dev]` | +5 行 |
| 5 | `tests/test_registry.py` | 新增外部发现测试 | +40 行 |

### 8.3 总改动统计

```
新增文件: 15
改动文件: 5
总代码增量: ~750 行
```

---

## 9. CLI 命令增补

在现有 `agentos` CLI 中新增 `capability` 子命令组：

```bash
agentos capability scaffold <name>          # 生成新 Capability 骨架
agentos capability discover [--dir <path>]  # 发现并注册外部 Capability
agentos capability validate <path>          # 验证 manifest + fn 签名
agentos capability list                     # 列出已注册的 Capability
```

```bash
# 示例会话
$ agentos capability scaffold hello-world --with-schema
✅ Capability 'hello-world' scaffolded at: ./hello-world/

$ agentos capability validate ./hello-world/
✅ Capability 'hello-world' manifest valid
✅ Handler signature: handler(task, context) → Optional[Any]

$ agentos capability discover --dir ./
✅ Discovered 1 capability: hello-world (v0.1.0)

$ agentos capability list
Registered capabilities (6):
  search [builtin v0.1.0]       tags: research, fetch
  llm    [builtin v0.1.0]       tags: analysis, ai
  ...
  hello-world [external v0.1.0] tags: demo, greeting
```

---

## 10. 30 分钟开发路径

### 路径 A — 命令行脚手架（5 分钟）

```bash
# Step 1: Scaffold (1 min)
agentos capability scaffold my-capability --with-schema

# Step 2: Edit handler.py (5 min)
# 打开 hello-world/handler.py 写业务逻辑

# Step 3: Edit manifest.yaml (2 min)
# 更新 task_type, description, tags, input/output schema

# Step 4: Validate (1 min)
agentos capability validate ./hello-world/

# Step 5: Test (10 min)
cd hello-world && pip install -r requirements.txt && pytest

# Step 6: Deploy — 注册到 Agent OS (1 min)
agentos capability discover --dir ./
```

### 路径 B — 手写（15 分钟）

1. 创建目录结构（2 min）
2. 写 `handler.py`（5 min）
3. 写 `manifest.yaml`（3 min）
4. 写 `__init__.py`（1 min）
5. 验证 + 注册（4 min）

### 路径 C — 从现有代码迁移（10 分钟）

已有 Python 函数的开发者只需：

1. 创建 `manifest.yaml` 描述元数据（3 min）
2. 在 YAML 中设置 `entry_point: my_module.my_func`（1 min）
3. 验证 + 注册（6 min）

---

## 11. 附录：SDK API Reference

### `agentos.sdk` 公开 API

```python
from agentos.sdk import (
    # 加载
    load_capability,         # load_capability(path, registry=None) -> CapabilityManifest
    discover_capabilities,   # discover_capabilities(path, registry=None) -> list[CapabilityManifest]
    discover_installed,      # discover_installed(registry=None) -> list[CapabilityManifest]

    # 验证
    validate_capability,     # validate_capability(manifest) -> dict {valid, errors, warnings}
    validate_manifest,       # validate_manifest(manifest) -> list[str]
    validate_fn_signature,   # validate_fn_signature(fn) -> list[str]

    # 脚手架
    scaffold,                # scaffold(name, output_dir=".", **options) -> Path

    # 工具
    package_as_capability,   # package_as_capability(path) -> CapabilityManifest
)
```

### Registry 扩展方法

```python
# registry/__init__.py 新增
class Registry:
    def discover_external(self, path: str | Path) -> list[CapabilityManifest]:
        """Discover and register external capabilities from a directory."""
        ...
```

---

## 12. 附录：扩展点（Future Work）

以下功能属于 SDK V2 范围，不在当前 RFC 中：

| 功能 | 优先级 | 说明 |
|------|--------|------|
| async handler 支持 | P2 | `async def handler(task, context)` |
| Capability 生命周期钩子 | P3 | `on_register`, `on_invoke`, `on_error` |
| Capability 版本管理 | P3 | 同时注册多个版本，按版本路由 |
| 远程 Capability | P3 | 通过 gRPC/HTTP 调用远程实现 |
| Capability 市场 | P4 | 中央注册表、发现、安装 |
| 类型安全的 Schema 校验 | P2 | 运行时校验 input/output 与 schema 匹配 |
