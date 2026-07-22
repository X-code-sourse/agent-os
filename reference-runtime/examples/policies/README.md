# Intent OS — Security Quickstart

## 1. 查看当前策略

```bash
intent-os security policy list
```

如果还没有任何策略，你会看到 `No policies found.`

## 2. 应用一个策略

应用开发环境策略（宽松——只拦截 critical 风险的能力）：

```bash
intent-os security policy apply examples/policies/development.yaml
```

预期输出：
```
Policy 'dev-default' applied (v1).
```

## 3. 验证策略生效

用策略引擎评估一个 Manifest：

```bash
intent-os security evaluate examples/text_summarize.yaml
```

输出应显示 `"decision": "allow"`——text_summarize 是 low 风险，宽松策略允许所有非 critical 的能力。

## 4. 查看审计报告

```bash
intent-os security audit
```

显示所有策略、启用状态、以及每种风险等级有多少个策略覆盖。

## 5. 内置策略级别

| 策略 | 文件 | 行为 |
|---|---|---|
| **宽松** | `examples/policies/development.yaml` | 只拦截 critical，自动放行 |
| **企业** | `examples/policies/enterprise.yaml` | 拦截 critical，高 file/process 风险 |
| **严格** | `examples/policies/strict.yaml` | 拦截 medium+，金融/payment 升高风险等级 |

## 6. 自定义策略

参考 `examples/policies/strict.yaml` 的格式创建自己的 YAML：

```yaml
policy_id: my-policy
description: "Custom policy"
target_patterns:
  - "financial.*"
risk_overrides:
  "financial.*": "critical"
review_rules:
  require_review_for:
    - critical
    - high
version: 1
enabled: true
```

关键字段：
- **target_patterns** — 策略应用于哪些能力（glob 通配符）
- **risk_overrides** — 把特定能力的风险级别提升/降低
- **review_rules.require_review_for** — 哪些风险级别需要人工审批

应用：`intent-os security policy apply my-policy.yaml`
