# Intent OS — Go-to-Market Plan

> **Product:** Intent OS — open-source flight recorder for AI agents  
> **Positioning:** "See exactly what your AI agent did."  
> **Version:** v0.4.2 | **Tests:** 709 pass | **License:** AGPLv3+Commercial  
> **ICP:** Python developers building or using AI coding agents

---

## Platform Priority Ranking

| Rank | Platform | Why | Effort | Expected Impact |
|------|----------|-----|--------|-----------------|
| **1** | **Hacker News** | Single post can drive thousands of pip installs. Your ICP lives here. | 2h (write) + 4h (respond) | 🔥🔥🔥🔥🔥 |
| **2** | **Reddit r/LocalLLaMA, r/MachineLearning** | Active AI engineering communities. Lower barrier than HN. | 1h per post | 🔥🔥🔥🔥 |
| **3** | **X/Twitter** | Build-in-public + developer reach. Add thread when HN post drops. | 30min per thread | 🔥🔥🔥 |
| **4** | **Python-focused newsletters** | Python Weekly, PyCoders, TLDR AI. Direct to ICP inbox. | 1h per submission | 🔥🔥🔥 |
| **5** | **GitHub Trending** | Byproduct of HN/Reddit traction. Not something you "post" to. | passive | 🔥🔥🔥 |
| **6** | **Discord / Slack (AI Engineer, LangChain, etc.)** | Niche but high-conversion. Share after HN post. | 30min | 🔥🔥 |
| **7** | **Dev.to / Medium** | Long-tail SEO value. Low urgency. | 2h per article | 🔥 |

---

## Platform 1: Hacker News (Primary Launch)

### Title (must be a problem, not a product)

```
Show HN: I built a flight recorder for AI coding agents
```

Why this works:
- "flight recorder" is a known concept — no explanation needed
- "AI coding agents" hits the exact ICP
- "I built" signals it's a solo project (HN loves this)
- It describes a problem, not a product

### Post Timing

| Element | Value |
|---------|-------|
| Day | **Tuesday or Wednesday** (highest engagement) |
| Time | **8:00 AM ET** (peak US + EU overlap) |
| Timezone | UTC-4 or UTC-5 depending on daylight saving |

### Post Content

First paragraph (these appear in the HN feed, make them count):

```
AI coding agents are black boxes. You tell them to do something,
they do it, and you have no idea what happened — which tools they
called, why they failed, or how much they cost.

I built an open-source flight recorder for AI agents. Point it at
your API endpoint, and every model call gets recorded into a
structured execution trace.

pip install intentos
intent-os doctor
```

### Comment Strategy

Be ready for these questions:

| Question | Answer |
|----------|--------|
| "How is this different from just logging API calls?" | It structures them — trace_id links every call into a single execution timeline. One intent -> 12 API calls -> 1 trace. |
| "Does it work with Claude Code?" | Yes, set `ANTHROPIC_BASE_URL` and every call is recorded. |
| "Does it work with Cursor?" | Yes, same pattern with `OPENAI_BASE_URL`. |
| "How is this different from [competitor]?" | It's open source (AGPLv3), runs locally, no cloud dependency. Your data never leaves your machine. |
| "Can I see what the output looks like?" | `pip install intentos && intent-os demo --auto` — 30 seconds. |
| "709 tests? Really?" | Yes — Python 3.10/3.11/3.12 matrix, 709 tests, 0 failures. |
| "Is this a business?" | Open source core. Commercial license for enterprise deployments (security audit, policy engine). |

### One Week Before HN Post

Post a "building in public" thread on X to build initial followers.

---

## Platform 2: Reddit

### r/LocalLLaMA — Best fit

**Title:**

```
I built an open-source black box for AI agents (inspect, debug, cost tracking)
```

**Content structure:**
1. Problem sentence (agents are black boxes)
2. One terminal screenshot showing `intent-os inspect latest`
3. `pip install intentos`
4. It's open source (AGPLv3)
5. Link to GitHub

**Best time:** Weekday midday US time.

### r/MachineLearning

**Title:**

```
[Project] Intent OS — open-source flight recorder for AI agents
```

**Content structure:** Same as above but more technical depth. Mention architecture (Event Store, proxy, 709 tests). This sub expects Show HN-style "here's what I built" posts.

---

## Platform 3: X/Twitter

### Launch Day Thread

```
1/ AI agents are black boxes.
   They call models, use tools, spend money — and you see none of it.

2/ I built an open-source flight recorder.
   pip install intentos

3/ One command:
   intent-os doctor
   → shows you exactly what your last agent run did

4/ Or see every step:
   intent-os inspect latest
   → full execution timeline with costs

5/ Works with Claude Code, Cursor, any OpenAI/Anthropic agent.
   Just set OPENAI_BASE_URL.

6/ 709 tests. AGPLv3. v0.4.2 on PyPI.
   https://github.com/haihaoxu/intentos

#opensource #AI #coding #developer
```

### Regular Posts (post-launch, 2-3/week)

```
"Claude Code just cost me $3 in API calls for one refactor.
 I only found out because I had the proxy running.
 intent-os doctor showed me exactly what happened."
```

```
"Every AI agent call is an event.
Events form a trace.
Traces tell you what happened.

That's all Intent OS does.
But it changes everything about how you debug agents."
```

```
"Your AI agent is a black box.
Your API bill isn't.

intent-os proxy start
→ every API call recorded
→ cost per model
→ cost per agent"

pip install intentos
```

---

## Platform 4: Developer Newsletters

| Newsletter | Submit URL | Angle |
|------------|-----------|-------|
| **Python Weekly** | https://pythonweekly.com/submit | "New open-source CLI tool: trace and debug your AI agents" |
| **PyCoders** | https://pycoders.com/submit | "Intent OS: flight recorder for AI coding agents" |
| **TLDR AI** | https://tldr.tech/ai/submit | "Open-source tool lets you see exactly what your AI agent did" |
| **The AI Edge** | similar | "Agent flight recorder reaches v0.4.2 — 709 tests, AGPLv3" |

Submission email template:

```
Subject: Intent OS — open-source flight recorder for AI agents

Intent OS is an open-source tool (AGPLv3) that records every
AI model call your coding agents make. 

Key features:
- Proxy: intercept OpenAI/Anthropic calls via environment variable
- Doctor: one-command agent health check
- Inspect: full execution timeline with cost tracking

pip install intentos
GitHub: https://github.com/haihaoxu/intentos
```

---

## Platform 5: GitHub Trending

This is automatic — if HN/Reddit get traction, GitHub stars will follow. Make sure:

- ✅ README is clean and positioned correctly (done)
- ✅ Description on repo is set (done: "Flight recorder for AI agents")
- ✅ Topics set: `ai`, `observability`, `agent`, `cli`, `python`, `llm`
- ✅ License file present (AGPLv3 — done)
- ✅ Issues are open for contributions

---

## Platform 6: Developer Discord / Slack

Share AFTER the HN post goes live. DO NOT share before.

| Community | Channel | Approach |
|-----------|---------|----------|
| **AI Engineer Discord** | #showcase | "Just launched on HN: flight recorder for AI agents" |
| **LangChain Discord** | #show-and-tell | "Open-source tool to trace your agent calls" |
| **MCP Discord** | #general | "Intent OS now has an Agent Hook proxy — records any agent's LLM calls" |

---

## Execution Calendar

### Day 1: HN Launch

| Time | Action |
|------|--------|
| 7:30 AM ET | Post on HN |
| 7:35 AM ET | Post same content as X thread |
| 8:00 AM ET | Monitor HN comments, respond to every question |
| 12:00 PM ET | Post to r/LocalLLaMA and r/MachineLearning |
| Continuous | Answer HN comments (this is the most important work) |

### Day 2-3: Aftermath

| Action | Detail |
|--------|--------|
| Submit to Python Weekly + PyCoders + TLDR AI | Use the template above |
| Post finished thread on X with lessons learned | What HN taught you |
| Monitor GitHub Issues | Fix any bugs users report |
| Read every comment carefully | Users will tell you what's missing |

### Week 2: Iterate

- Fix the top 3 complaints from HN comments
- If > 100 stars, add a "Users" section to README
- Post a "What I learned from launching on HN" blog post

---

## Success Metrics

| Metric | Good | Great | Amazing |
|--------|------|-------|---------|
| pip installs (week 1) | 100 | 500 | 2000+ |
| GitHub stars (week 1) | 50 | 200 | 500+ |
| HN upvotes | 50 | 150 | 300+ |
| Issues opened | 1 | 5 | 15+ |
| First commercial inquiry | — | — | 1+ |

---

## What NOT To Do

| Don't | Why |
|-------|-----|
| Post on LinkedIn | Your ICP is not there |
| Make a landing page | README is your landing page |
| Run ads | Way too early, too broad |
| Spam every subreddit | One good post > ten okay posts |
| Argue with HN comments | Thank them for feedback, fix it |
| Post before you have time to respond | HN window is ~6 hours |
