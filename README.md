# LLM Router Demo

A minimal multi-model router demo, inspired by [Poe](https://poe.com/): dispatch each request to a different-priced LLM based on task difficulty to save token costs.

**This is a mock demo** — no real LLM APIs are called.

## Motivation

LLM prices vary by ~100× (Opus vs. GPT-4o-mini), yet many everyday tasks (translation, summarization, formatting) run perfectly well on cheap models. The router's goal:

> Auto-classify task difficulty → pick the cheapest model that's good enough → save money without hurting UX.

## Routing Strategies

Two routing modes are implemented side-by-side for comparison:

### Mode 1: Rule-based (`mode=rule`, default)

Fast and explainable — pure keyword + length classification, no model calls:

| Trigger | Tier | Default model |
|---------|------|---------|
| Hits "translate / summarize / 翻译 / 总结…" or prompt < 80 chars | `cheap` | gpt-4o-mini |
| Hits "code / function / implement / fix…" or contains ` ``` ` block | `mid` | sonnet-4.6 |
| Hits "analyze / prove / why / 分析 / 证明…" or long code block | `top` | opus-4.7 |
| Detected ≥3 numbered steps (`1. 2. 3.`) | bump up one tier | |

Every routing decision prints exactly which rule fired — easy to debug and reason about.

### Mode 2: LLM Dispatcher (`mode=llm`)

A cheap "dispatcher" model (haiku-4.5) classifies difficulty, then forwards the prompt to the execution model. **This demo mocks the dispatcher** with a more refined rule function (weighted keywords / negation detection / phrase patterns), and accounts for the dispatcher's own token cost.

```
prompt
  │
  ▼  ① dispatcher (haiku-4.5, ~$0.00005/call)
  │    output: {"tier": "mid", "score": 1.5, "reason": "code-related"}
  ▼
  ② execution model (gpt-4o-mini / sonnet-4.6 / opus-4.7)
```

**Short-circuit**: prompts < 18 chars skip the dispatcher entirely and fall back to rules.

**Where the dispatcher beats rules**:
- Negation handling ("don't give me code…" → won't mis-route to mid just because "code" is mentioned)
- Weighted scoring instead of first-keyword-wins
- Phrase patterns (`why...?` → top; `^translate:` → forced cheap)

**Dispatcher is not free**: it spends tokens itself, and **only pays off on ambiguous/adversarial prompts**. On clear-cut prompts, rules are free and equally accurate — see comparison below.

## Usage

```bash
# Run the full built-in demo (single prompts + multi-agent tasks)
python3 router.py

# Route a single prompt (prints both rule and llm modes)
python3 router.py "write a Python function to deduplicate a list"
```

No dependencies — pure Python stdlib.

## Example Output

```
PROMPT : write a Python function to deduplicate a list while preserving order
MODE   : rule   →   TIER: mid   MODEL: sonnet-4.6
REASON :
   • hit code/implementation keywords: ['function']
   • picked tier=mid default model: sonnet-4.6
TOKENS : in=6  out=9
COST   : $0.000153
         baseline opus-4.7: $0.000765, saved $0.000612 / 80.0%
QUALITY: 9/10   (baseline opus-4.7: 9/10)
```

## UX Quality Score (mock)

Each routed call gets a 1–10 quality score, so you can tell whether saving money hurt UX:

| Model tier vs task tier | Quality |
|-------------------------|--------:|
| Model = task difficulty (perfect match) | 9 |
| Model > task difficulty (over-spec) | 10 |
| Model < task difficulty by 1 tier | 6 |
| Model < task difficulty by 2 tiers | 3 |

## Rules vs Dispatcher — Adversarial Comparison

Running `python3 router.py` prints this table (excerpt):

```
PROMPT                                            rule              llm-dispatch
Don't give me code, just describe the dedup       opus-4.7  q9 ⚠   gpt-4o-mini  q9 ✅
  algorithm idea in words
Translate this and analyze the author's tone:     opus-4.7  q9 ⚠   gpt-4o-mini  q9 ✅
  "The weather is unexpectedly nice today."
Why does this code have a race condition?         opus-4.7  q9 ✅   opus-4.7     q9 ✅
  Please analyze in depth.
```

In the first two, rules wrongly escalate to opus (misled by keywords like "algorithm" / "analyze"). The dispatcher catches the negation and the simple-intent phrases to correctly downgrade to cheap → ~100× savings.

## Multi-Agent Tasks

A complex task usually decomposes into multiple sub-steps of varying difficulty. The demo includes two example tasks (news aggregator bot / code review for a concurrency module). Each subtask is labeled with its true difficulty, and we compare **4 strategies**:

| Strategy | Idea | When it wins |
|----------|------|--------------|
| `all-cheap` | Use cheap model everywhere | Aggressive savings, but hard tasks collapse |
| `routed` | Rule-based routing | Balanced, zero routing overhead ✅ |
| `llm-dispatch` | LLM dispatcher | Same quality on unambiguous tasks but pays dispatcher overhead |
| `all-top` | Use top model everywhere | Max quality, wasteful |

Output for the news aggregator task:

```
all-cheap     $0.000034   7.2/10   ← hard subtasks collapsed
routed        $0.001078   9.0/10   ← rules are sufficient
llm-dispatch  $0.002262   9.0/10   [dispatcher cost $0.001184 — pure overhead]
all-top       $0.004185   9.8/10
```

**Takeaway**: on clear-cut tasks, the dispatcher is pure waste. It only pays off on ambiguous/adversarial prompts. In production, aggressive short-circuiting (length, allowlist keywords, caching classifications) is needed to keep dispatcher calls low enough to break even.

## Model Pool (mock prices, ~2026 market)

| Model | Tier | Input $/1M | Output $/1M |
|-------|------|-----------:|------------:|
| gpt-4o-mini    | cheap | 0.15  | 0.60  |
| deepseek-chat  | cheap | 0.27  | 1.10  |
| haiku-4.5      | cheap | 1.00  | 5.00  |
| sonnet-4.6     | mid   | 3.00  | 15.00 |
| gpt-4o         | mid   | 2.50  | 10.00 |
| opus-4.7       | top   | 15.00 | 75.00 |

## Swapping in Real APIs

Only two functions in `router.py` need to change:

1. `mock_call()` → replace with `openai` / `anthropic` SDK calls
2. `dispatch_with_llm()` → replace the mock rule body with a real Haiku call returning the same `RouteDecision` shape

The `MODELS` price table stays — just plug real token counts from the API response into `cost()`.

## License

MIT
