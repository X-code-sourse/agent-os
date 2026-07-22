# Intent OS — 发布方案

---

## 唯一第一帖（现在）：r/LocalLLaMA

不要同时发多个 subreddit。观察反馈后再决定下一站。

**Title:**

I built an open-source flight recorder for AI agents — see exactly what they did, why they failed, and what they cost

**Body:**

AI agents are becoming useful, but debugging them is still painful.

You give an agent a task, wait a few minutes, and if something goes wrong you often don't know:

- which tools it called
- where the execution failed
- how much it cost

I kept running into this while building agents, so I built Intent OS — an open-source flight recorder for AI agents.

```bash
pip install intentos

# Check your last run
intent-os doctor

# See the execution timeline
intent-os inspect latest
```

Example output:

```
[14:02:01] START
[14:02:09] MODEL CALL  claude-sonnet-4  (2,451 tokens)
[14:02:14] TOOL        filesystem.write
[14:02:27] FAILED      test_jwt_verify failed
```

It works through a lightweight local proxy. Existing agents can be observed without changing application code — just set an environment variable.

Everything runs locally. Execution data stays on your machine.

Currently:
- Python package on PyPI (v0.4.2)
- AGPLv3 + commercial license
- 709 tests

Would love feedback from people building agents: what information do you wish you had when an agent failed?

GitHub: https://github.com/haihaoxu/intentos

---

## 后续步骤（看第一帖反馈）

| 反馈信号 | 下一步 |
|----------|--------|
| 有人问"支持 X 吗" | 第二帖发 r/Python |
| 有人质疑"和 Y 比怎样" | 第三帖发 r/artificialintelligence |
| 没人理 | 调整标题/正文后重试 |
| HN karma 攒够 | 发 HN（帖子正文在下方）|

---

## HN 正文（届时作为第一个 comment）

AI coding agents are becoming useful, but they are still black boxes.

You give them a task, they run for minutes, and when something goes wrong you often don't know:

- which tools they called
- where they failed
- how much they spent

I built an open-source flight recorder for AI agents.

```bash
pip install intentos

intent-os doctor
intent-os inspect latest
```

It works as a lightweight proxy that records every OpenAI and Anthropic API call.

```bash
intent-os proxy start
export OPENAI_BASE_URL=http://localhost:8377
```

Everything runs locally. Your data never leaves your machine.

```
[14:02:01] > START
[14:02:09] > MODEL CALL  claude-sonnet-4  (2,451 tokens)
[14:02:14] > TOOL        filesystem.write
[14:02:27] !! FAILED     test_jwt_verify failed
```

Built solo. v0.4.2. 709 tests. AGPLv3 + commercial option.

https://github.com/haihaoxu/intentos
pip install intentos
