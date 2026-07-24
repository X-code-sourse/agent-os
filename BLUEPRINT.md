# Intent OS — Blueprint

> **从 Flight Recorder 到 Agent Execution Infrastructure 的完整路线图**
>
> 最后更新：2026-07-23
> 对应代码：v0.4.3 (731 tests)

---

## 一句话

> **Intent OS is building the portable execution contract for AI agents — the missing infrastructure layer between Agent Capabilities and Runtimes.**
>
> When a developer creates an Agent, the Execution Contract defines who it is, what it can do, what environment it needs, what it actually did, whether its claims are provable, and whether its actions were authorized. That contract must be valid on Claude, on OpenAI, on Ollama, on any runtime. This is the HTTP/Docker/Kubernetes of the AI Agent era.

---

## 六层架构 — 全部服务于一个目的：Agent Accountability

AI agents are crossing a line. They used to answer questions. Now they modify code, call APIs, write files, spend money — all on their own. But they have no identity card, no audit trail, no permission boundary, no way to prove their decisions were justified.

The six layers of Intent OS are not arbitrary. Each one answers a specific accountability question:

```
Layer 1 — Context        "What was the agent supposed to do?"
Layer 2 — Identity       "Who is this agent, and who does it represent?"
Layer 3 — Execution      "What did it actually do?"
Layer 4 — Verification   "Can we prove its claims are true?"
Layer 5 — Governance     "Was it allowed to do that?"
Layer 6 — Interoperability "Can its capabilities be discovered, reused, and trusted by others?"
```

Together, they form an **Agent Accountability System** — the equivalent for autonomous AI of what audit trails are to finance and what version control is to software.

```
                        Human / Organization
                                │
                                │  "Who authorized this?"
Layer 1 ┌───────────────────────────────────┐
        │         Context Layer             │
        │  "What was it supposed to do?"     │
        └───────────────────────────────────┘
                                │
                                │
Layer 2 ┌───────────────────────────────────┐
        │        Identity Layer             │
        │  "Who is this agent?"              │
        └───────────────────────────────────┘
                                │
                                │
Layer 3 ┌───────────────────────────────────┐
        │       Execution Layer             │
        │  "What did it actually do?"        │  ← 当前入口
        └───────────────────────────────────┘
                                │
                                │
Layer 4 ┌───────────────────────────────────┐
        │      Verification Layer           │
        │  "Can we prove its claims?"        │
        └───────────────────────────────────┘
                                │
                                │
Layer 5 ┌───────────────────────────────────┐
        │       Governance Layer            │
        │  "Was it allowed to do that?"      │
        └───────────────────────────────────┘
                                │
                                │
Layer 6 ┌───────────────────────────────────┐
        │     Interoperability Layer        │
        │  "Can others discover and trust    │
        │   its capabilities?"              │
        └───────────────────────────────────┘
```

**依赖关系：下层是上层的数据来源。没有 Execution Record，就无法验证、无法治理、无法互操作。**

---

## 现状映射：v0.4.3 已有什么

| 层 | 已有模块 | 状态 | 差距 |
|----|---------|------|------|
| **Context** | `context_store.py`, `commands/context.py` | ✅ Phase 2 骨架 | 6 CLI 命令，完整 CRUD |
| **Identity** | `agent_store.py`, `commands/agent.py` | ✅ Phase 2 完整 | Agent + Team + Capability + Status 全部到位 |
| **Execution** | `event_store.py`, `recorder.py`, `proxy/`, `execution_analytics.py`, `commands/{trace,doctor,cost,inspect,analytics}.py` | ✅ 主力 + Analytics | 核心链路 + Streaming + Agent 分析 + 异常检测 |
| **Verification** | `evidence_store.py`, `commands/evidence.py` | ✅ Phase 3 骨架 | 5 CLI 命令，FK 约束，source_type 校验 |
| **Governance** | `security.py`, `guard.py`, `commands/{scan,audit,security}.py` | ⚡ Phase 0 | 同步评估。Phase 3 升级在 BLUEPRINT 3.2 规划 |
| **Interop** | `models.py`(Manifest), `parser.py`, `adapters/`, `registry.py`, `federated.py` | ⚡ Phase 3 市场 | Manifest 冻结 + Marketplace publish/discover/show/install/rate |

### 关键数据流（当前）

```
AI Agent
    │
    ▼
Proxy (server.py)         ◄── 零侵入拦截
    │
    ├─► AgentTracer        → EventStore (events.db)
    │                         ├── events 表 (26 种 EventType)
    │                         ├── execution_records 表
    │                         └── task_state 表
    │
    ├─► ToolCallGuard      → 30+ 工具风险分类
    │
    └─► LLM API (OpenAI / Anthropic)

CLI Layer:
    doctor     ← 读取最近 Execution → 诊断失败
    inspect    ← 读取 events + records → Timeline
    cost       ← 聚合 LlmCall events → 费用报告
    scan       ← 扫描 events + Guard 分类 → 安全报告
    audit      ← 聚合 records + security events → 合规报告
```

---

## Phase 1: Flight Recorder（2026）— 当前阶段

### 目标

**让 1000 个开发者安装 `pip install intentos`，并且 10 个连续使用 7 天。**

### 已交付 ✅

| 模块 | 功能 |
|------|------|
| `proxy start` | HTTP 代理，拦截 OpenAI/Anthropic，SSE streaming |
| `proxy doctor` | 代理健康检查：状态、流量、Agent 分布 |
| `doctor` | Agent 最后一次执行的健康诊断 |
| `inspect latest` | 完整执行时间线（Terminal + HTML 导出） |
| `cost` | 按 agent/模型/日期的费用追踪 |
| `agent create/list/get` | Agent 身份注册 |
| `scan` | 安全扫描：危险工具 + 敏感数据检测 |
| `audit report` | 合规审计报告（CSV/HTML/JSON） |
| `event prune` | 数据清理，用户控制磁盘 |
| `demo --auto` | 30 秒零配置演示 |

### P0 剩下的（发布前）

- [ ] **PyPI 重新上传** — `pyproject.toml` 已修正（AGPLv3, keywords, classifiers），等你 token
- [ ] **README 已重写** — 首屏："Your AI agent ran for 20 minutes. It says 'done.' Can you explain what it did?"
- [ ] **分发** — HN / Reddit / X / 知乎（方案在 `HN_POST.md`, `GO_TO_MARKET.md`, `CONTENT_PLAN.md`）

### Phase 1 的 go/no-go

| 指标 | 达标标准 | 当前 |
|------|---------|------|
| pip installs（外部，非 clone） | ≥ 100 | 0 |
| GitHub stars | ≥ 50 | ? |
| 陌生人开的 Issue | ≥ 1 | 0 |
| 连续 7 天活跃用户 | ≥ 5 | 0 |

**如果 Phase 1 没有达到这些指标：不要进入 Phase 2。回头修产品。**

---

## Phase 2: Agent Management Layer（2027）

### 前置条件
- Phase 1 go/no-go 全部达标
- ≥ 20 外部用户愿意提供反馈
- 有人在 Issue 里问 "我怎么管理多个 Agent"

### 核心交付

#### 2.1 Agent Registry 完善

**数据模型：**
```python
# 扩展 Agent 模型 (agent_store.py)
@dataclass
class Agent:
    agent_id: str           # agent_a82f91c3
    name: str
    description: str
    owner: str              # 新增：所属用户/团队
    team_id: str | None     # 新增：团队 ID
    capabilities: list[str] # 新增：已注册的能力列表
    policy_ids: list[str]   # 新增：关联的安全策略
    created_at: str
    last_seen_at: str | None
    status: str             # active | paused | revoked
```

**CLI：**
```bash
intent-os agent team create --name "Research Team"
intent-os agent team add <agent_id> <team_id>
intent-os agent capability grant <agent_id> <capability>
intent-os agent status <agent_id>
```

#### 2.2 Execution Analytics

**新建模块：** `core/execution_analytics.py`

**功能：**
- 按 Agent 聚合：成功率、平均延迟、Top 失败原因
- 按时间趋势：日/周/月执行量、费用趋势
- 异常检测：单次执行费用突增、延迟飙升
- Agent 对比：同任务不同 Agent/模型的效率对比

**CLI：**
```bash
intent-os analytics agent <agent_id>           # 单个 Agent 全维度分析
intent-os analytics compare <agent_a> <agent_b> # 两个 Agent 对比
intent-os analytics anomaly --since 7d          # 近 7 天异常检测
```

#### 2.3 Context Layer（第一版）

**这是个新层——之前完全没有。第一版做最小可行的 Execution Context。**

**数据模型：**
```python
@dataclass
class ExecutionContext:
    """Agent 执行任务所需的环境快照。"""
    context_id: str          # ctx_<uuid>
    name: str                # e.g., "US Stock Analysis Project"
    goal: str                # e.g., "Find undervalued companies"
    constraints: list[str]   # e.g., ["SEC sources only", "No speculation"]
    task_scope: str          # e.g., "research" | "trading" | "analysis"
    variables: dict          # e.g., {"tickers": ["TSLA","AAPL"], "period": "Q1 2026"}
    parent_context_id: str | None  # 继承自哪个 Context
    created_by: str          # Agent ID or User ID
    created_at: str
    expires_at: str | None
```

**SQLite 表：**
```sql
CREATE TABLE execution_contexts (
    context_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    goal TEXT NOT NULL,
    constraints TEXT NOT NULL DEFAULT '[]',   -- JSON array
    task_scope TEXT,
    variables TEXT NOT NULL DEFAULT '{}',      -- JSON object
    parent_context_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE context_assignments (
    context_id TEXT,
    agent_id TEXT,
    assigned_at TEXT,
    PRIMARY KEY (context_id, agent_id)
);
```

**核心原则：Context 不是 Memory。** Context 不记录"用户的喜好"——它只记录"Agent 执行所需的环境约束"。Memory 是另一个产品（Phase 3+）。

**CLI：**
```bash
intent-os context create --name "X Project" --goal "..." --constraint "..."
intent-os context assign <context_id> <agent_id>
intent-os context list --agent <agent_id>
intent-os context inspect <context_id>
```

**Context 和 Execution 的关系：**
```
Context (ctx_001)
    │
    ├── Execution (exec_001)  ← Agent 在此 Context 下执行
    │   ├── Events
    │   └── Record
    │
    ├── Execution (exec_002)
    │   └── ...
    │
    └── Context History      ← 同一 Context 下所有 Execution 的聚合分析
```

Execution Record 新增字段：
```sql
ALTER TABLE execution_records ADD COLUMN context_id TEXT;
```

#### 2.4 团队功能

**数据模型：**
```python
@dataclass
class Team:
    team_id: str
    name: str
    owner: str
    member_ids: list[str]
    created_at: str
```

**功能：**
- 团队创建 + 成员管理
- Agent 归属团队
- 按团队的费用聚合
- 按团队的策略继承

---

## Phase 3: Agent Execution Infrastructure（2028+）

### 前置条件
- Phase 2 在企业环境有 ≥ 3 个付费客户
- Event Store 积累 ≥ 100,000 条 Execution Record
- 有人问 "我的 Agent 能不能在另一个平台用"

### 核心交付

#### 3.1 Verification Layer（验证层）

**这是一个全新的层——目前完全没有。**

**数据模型：**
```python
@dataclass
class Evidence:
    """Agent 输出的可验证证据。"""
    evidence_id: str
    execution_id: str        # 关联到哪个 Execution
    claim: str               # Agent 的主张，e.g., "Tesla margin decreased"
    source_type: str         # "data" | "calculation" | "model_inference" | "external_api"
    source_ref: str          # e.g., "SEC filing page 43", "database query result"
    raw_data_ref: str        # 指向原始数据（可存在 Event Store 或外部存储）
    confidence: float        # 0.0 - 1.0
    verified: bool           # 是否经过人工/自动验证
    verified_by: str | None  # 验证人/系统
    verified_at: str | None
```

**SQLite 表：**
```sql
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    raw_data_ref TEXT,
    confidence REAL NOT NULL DEFAULT 0.0,
    verified INTEGER NOT NULL DEFAULT 0,
    verified_by TEXT,
    verified_at TEXT,
    FOREIGN KEY (execution_id) REFERENCES execution_records(trace_id)
);
```

**CLI：**
```bash
intent-os evidence list <execution_id>       # 某个 Execution 的所有证据
intent-os evidence verify <evidence_id>      # 人工标记为已验证
intent-os evidence chain <execution_id>      # 证据链：输入→推理→输出
```

**和 Execution Record 的关系：**
```
Execution (exec_001)
    │
    ├── TaskStarted
    ├── CapabilityInvoked
    ├── TaskCompleted
    │   └── output: "Tesla margin decreased to 15%"
    │
    └── Evidence (联动)
        ├── evidence_001: claim="margin decreased", source="SEC filing", confidence=0.91
        ├── evidence_002: claim="15% margin", source="calculation: 18%-3%", confidence=0.85
        └── evidence_003: chain=[evidence_001, evidence_002] → output
```

#### 3.2 Governance Layer 升级

**从 v0.4.3 同步评估升级为 SPEC-0004 完整实现：**

| 当前 | Phase 3 |
|------|---------|
| 同步函数调用 | 事件驱动 pub/sub 架构 |
| 单 Policy 匹配 | 分层覆盖：Org → Team → User → Runtime |
| 无 Human Review | 完整 Review 流程 + 超时自动拒绝 |
| 无签名验证 | Manifest Ed25519 签名 |
| 仅 PolicyEvaluated | 全部 7 种 Security Event |
| `guard.py` 硬编码 | 类型化 Permission Descriptor 系统 |
| SQLite PolicyStore | 版本化 Policy 管理 |

**Policy 格式升级：**
```yaml
kind: SecurityPolicy
metadata:
  name: enterprise_default
  version: 1.0.0
  publisher: org.example

spec:
  applies_to:
    agents: ["agent_research_*"]
    capabilities: ["financial_*"]
    contexts: ["production_*"]

  risk_overrides:
    - target: "payment_exec"
      max_allowed: critical
      default_action: require_review

  permissions:
    allow:
      - filesystem_read
      - network_outbound
    deny:
      - process_exec
      - payment_exec
    require_review:
      - email_send
      - user_data_write

  review:
    timeout: 3600s
    escalation: admin

  audit:
    level: all
    retention_days: 90
```

#### 3.3 Agent Marketplace & Capability Registry

**这是 Interoperability Layer 的实际产品形态。**

**数据模型：**
```python
@dataclass
class CapabilityEntry:
    """在 Registry 中注册的 Capability——不只是本地，可以被其他 Agent 发现。"""
    capability_id: str       # name@version
    manifest: CapabilityManifest
    publisher: str           # Agent ID or Org ID
    visibility: str          # public | team | private
    verified: bool           # 是否经过验证
    usage_count: int         # 被调用的次数
    rating: float            # 用户/系统评分
    created_at: str
    updated_at: str
```

**CLI：**
```bash
intent-os registry publish <manifest>        # 发布到 Registry
intent-os registry discover "financial"      # 搜索可用 Capability
intent-os registry install <capability_id>   # 安装到本地 Agent
intent-os registry rate <capability_id> 4.5  # 评分
```

**跨 Agent 调用流程：**
```
Agent A (Research)
    │
    ├── intent-os registry discover "financial analysis" → 找到 Agent B 的 capability
    │
    ├── intent-os capability invoke financial_analyze@1.0.0 --input company=TSLA
    │
    └── Agent B's Execution Record: exec_xxx (invoked by Agent A, context ctx_001)
        └── 代理链可追溯
```

#### 3.4 Federated Registry

**SPEC-0006 从 stub 升级到完整实现：**

- Registry Identity (Ed25519 key pair)
- Peer Discovery (well-known endpoint + static config)
- Cross-Registry Query with signatures
- Trust Levels: none → query → sync → mirror
- Content-addressable Manifest retrieval by digest

---

## 完整依赖图

```
                    ┌──────────────────────┐
                    │   Context Layer       │
                    │   (execution_context)  │
                    └──────────┬───────────┘
                               │ context_id
                    ┌──────────▼───────────┐
                    │   Identity Layer      │
                    │   (agents, teams)     │
                    └──────────┬───────────┘
                               │ agent_id
                    ┌──────────▼───────────┐
                    │   Execution Layer     │
                    │   (events, records)   │  ← 数据引擎
                    └──┬──────┬──────┬─────┘
                       │      │      │
              ┌────────▼─┐ ┌──▼────┐ ┌▼─────────┐
              │Verification│ │Govern.│ │Interop.   │
              │(evidence)  │ │(policy)│ │(manifest) │
              └────────────┘ └───────┘ └───────────┘
```

**关键约束：**
1. Execution Layer 必须先做强——没有足够多、足够干净的 Execution Record，上面的 Verification 和 Governance 没有数据可用
2. Identity Layer 必须先做强——没有 Agent ID，无法关联 Execution → Agent → Team → Policy
3. Context 是横切层——它不依赖 Execution，但 Execution 引用它

---

## 数据模型全景图（最终态）

```
┌─────────────────────────────────────────────────────────────┐
│                        SQLite (intent.db)                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  agents                    execution_contexts               │
│  ┌──────────────────┐     ┌──────────────────────┐         │
│  │ agent_id (PK)    │     │ context_id (PK)      │         │
│  │ name             │     │ name                 │         │
│  │ owner            │     │ goal                 │         │
│  │ team_id (FK)     │     │ constraints (JSON)   │         │
│  │ capabilities     │     │ variables (JSON)     │         │
│  │ policy_ids (JSON)│     │ created_by (FK→agent)│         │
│  │ status           │     │ ...                  │         │
│  └──────────────────┘     └──────────────────────┘         │
│                                                             │
│  teams                     evidence                         │
│  ┌──────────────────┐     ┌──────────────────────┐         │
│  │ team_id (PK)     │     │ evidence_id (PK)     │         │
│  │ name             │     │ execution_id (FK)    │         │
│  │ owner            │     │ claim               │         │
│  │ member_ids (JSON)   │     │ source_type         │         │
│  └──────────────────┘     │ source_ref          │         │
│                           │ confidence          │         │
│  policies                 │ verified            │         │
│  ┌──────────────────┐     └──────────────────────┘         │
│  │ policy_id (PK)   │                                      │
│  │ target_patterns  │     events                           │
│  │ risk_overrides   │     ┌──────────────────────┐         │
│  │ permissions      │     │ id (PK)              │         │
│  │ review_rules     │     │ event_id (UNIQUE)    │         │
│  │ version          │     │ trace_id             │         │
│  └──────────────────┘     │ event_type           │         │
│                           │ ...                  │         │
│  capabilities             └──────────────────────┘         │
│  ┌──────────────────┐                                      │
│  │ cap_id (PK)      │     execution_records                │
│  │ manifest_yaml    │     ┌──────────────────────┐         │
│  │ publisher (FK)   │     │ trace_id (PK)        │         │
│  │ visibility       │     │ context_id (FK)      │         │
│  │ usage_count      │     │ agent_id (FK)        │         │
│  └──────────────────┘     │ ...                  │         │
│                           └──────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

---

## 团队规模 & 节奏建议

| 阶段 | 团队 | 时间 | 核心动作 |
|------|------|------|---------|
| Phase 1 | 1 人 | 2026 | Flight Recorder → 获取用户 → 收集反馈 |
| Phase 2.1 | 1-2 人 | 2026 Q4-2027 Q1 | Agent Registry 完善 + Execution Analytics |
| Phase 2.2 | 2-3 人 | 2027 Q2-Q3 | Context Layer v1 + Team 功能 |
| Phase 2.3 | 2-3 人 | 2027 Q4 | 第一个企业付费客户 |
| Phase 3.1 | 3-5 人 | 2028 | Verification Layer + Governance 升级 |
| Phase 3.2 | 5-8 人 | 2028-2029 | Marketplace + Federated Registry |

### 招聘顺序（当有收入时）

1. **第一个 hire：Developer Advocate / 社区** — 不是工程师。有人专门回答 Issue、写教程、收集反馈。
2. **第二个 hire：Backend/Infra Engineer** — 把 SQLite → 可扩展存储（但保持本地优先）。
3. **第三个 hire：Security Engineer** — Governance Layer 需要专业安全背景。

---

## 现在最重要的三件事

在回到写代码之前，先做这三件：

### 1. 你自己成为一号用户

把 `intent-os proxy start` 在你自己的 Claude Code 终端里开着，跑一周。你会在用的过程中发现：
- 哪些输出格式让人困惑
- `doctor` 的诊断是否真的有用
- `cost` 的汇总是否符合直觉
- 哪些 bug 只有每天用才会触发

**你自己的痛点是产品最好的指南针。**

### 2. 发布到 PyPI

```bash
cd ~/Desktop/intent-os/reference-runtime
python -m build
python -m twine upload dist/*
```

`pyproject.toml` 已经修正。README 已经重写。License 正确。Keywords 覆盖 Claude Code + Cursor 的搜索。不需要再等。

### 3. 找一个陌生人让他跑 30 秒

不是同事。不是朋友。是一个刚好用 Claude Code 的陌生人。给他：
```
pip install intentos
intent-os demo --auto
intent-os proxy start
```
然后闭嘴。看他卡在哪里。他说出 "oh, I get it" 的那一刻——那才是产品真正有效的时刻。

---

## 附录：当前代码归档

### 六层 → 代码模块映射

| 层 | 代码模块 | CLIs |
|----|---------|------|
| **Context** | `core/context_store.py` | `intent-os context *` |
| **Identity** | `core/agent_store.py` | `intent-os agent *` |
| **Execution** | `core/event_store.py`, `core/recorder.py`, `proxy/*` | `intent-os {doctor,inspect,cost,proxy*} *` |
| **Verification** | `core/evidence_store.py` | `intent-os evidence *` |
| **Governance** | `core/security.py`, `proxy/guard.py` | `intent-os {security,scan,audit} *` |
| **Interop** | `core/parser.py`, `core/registry.py`, `core/federated.py`, `adapters/*` | `intent-os {run,validate,compare,registry} *` |

### 26 个 Python 模块 × 当前成熟度

| 模块 | 行数 | 成熟度 | 说明 |
|------|------|--------|------|
| `event_store.py` | ~910 | ✅ 主力 | 26 种 EventType, prune, stats, traffic |
| `security.py` | ~940 | ⚡ Phase 0 | 同步评估, PolicyStore, 决策树 |
| `execution_analytics.py` | ~1029 | ✅ NEW | Agent 分析, 对比, 异常检测 |
| `scheduler.py` | ~600 | ✅ 主力 | 状态机, 重试, 超时, 失败传播 |
| `planner.py` | ~825 | ✅ | 数据分析驱动 + 多计划枚举 |
| `workflow.py` | ~632 | ✅ | DAG + ExecutionSemantics (7 种 policy) |
| `registry.py` | ~560 | ✅ | Capability CRUD + Marketplace publish/discover |
| `llm_provider.py` | ~517 | ✅ | Ollama/OpenAI/Anthropic/Auto |
| `cost_model.py` | ~512 | ✅ | 成本预估 |
| `ask.py` | ~441 | ✅ | 自然语言会话引擎 |
| `analytics.py` | ~404 | ✅ | 执行分析引擎 |
| `executor.py` | ~342 | ✅ | 执行中枢 |
| `models.py` | ~446 | ✅ | 全部数据模型 + Context/Evidence/Team/CapabilityEntry |
| `recorder.py` | ~340 | ✅ | 事件记录器 |
| `agent_store.py` | ~346 | ✅ Phase 2 | Agent + Team CRUD + Schema migration |
| `commands/analytics.py` | ~260 | ✅ | 10 subcommands (含 agent/compare/anomaly) |
| `commands/agent.py` | ~460 | ✅ | 12 subcommands (含 status/capability/team) |
| `context_store.py` | ~239 | ✅ NEW | Execution Context CRUD |
| `evidence_store.py` | ~236 | ✅ NEW | Evidence CRUD + FK + validation |
| `search.py` | ~323 | ✅ | TF-IDF 搜索引擎 |
| `parser.py` | ~320 | ✅ | Manifest YAML 解析 |
| `proxy/server.py` | ~340 | ✅ | HTTP 代理 + streaming |
| `federated.py` | ~268 | 🔮 Stub | 仅 PeerInfo + 基本查询 |
| `proxy/guard.py` | ~233 | ⚡ | 30+ 硬编码工具风险 |
| `proxy/tracer.py` | ~180 | ✅ | LlmCall 事件记录 |
| `workflow_parser.py` | ~384 | ✅ | Workflow YAML 解析 |
| `evolution.py` | ~201 | 🔮 | Evolution Loop |
| `conditions.py` | ~200 | ✅ | 条件 DSL |

### 6 个 Adapter

| Adapter | 行数 | 协议 |
|---------|------|------|
| `openai_adapter.py` | 228 | OpenAI Chat Completions |
| `anthropic_adapter.py` | 195 | Anthropic Messages |
| `ollama_adapter.py` | 199 | Ollama Native API |
| `github_models_adapter.py` | 194 | GitHub Models |
| `openrouter_adapter.py` | 162 | OpenRouter API |
| `base.py` | 94 | AdapterBase 抽象基类 |
