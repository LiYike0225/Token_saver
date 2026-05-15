"""
LLM Router Demo — 根据任务难度把请求分发到合适的模型，省 token 成本。

两种模式:
    python router.py                  # 跑内置 demo (单条 prompt + 多 agent 协作)
    python router.py "你的问题..."     # 路由单条 prompt
"""

import re
import sys
from dataclasses import dataclass, field


# ---------- 模型池 ----------
# 价格单位: USD per 1M tokens (input, output)，按 2026 年大致市价 mock
@dataclass
class Model:
    name: str
    tier: str          # cheap / mid / top
    price_in: float
    price_out: float

MODELS = {
    "gpt-4o-mini":   Model("gpt-4o-mini",   "cheap", 0.15,  0.60),
    "deepseek-chat": Model("deepseek-chat", "cheap", 0.27,  1.10),
    "haiku-4.5":     Model("haiku-4.5",     "cheap", 1.00,  5.00),
    "sonnet-4.6":    Model("sonnet-4.6",    "mid",   3.00, 15.00),
    "gpt-4o":        Model("gpt-4o",        "mid",   2.50, 10.00),
    "opus-4.7":      Model("opus-4.7",      "top",  15.00, 75.00),
}

TIER_DEFAULT = {
    "cheap": "gpt-4o-mini",
    "mid":   "sonnet-4.6",
    "top":   "opus-4.7",
}

# 对比基线：如果不用路由，全部丢给 top 模型的话
BASELINE_MODEL = "opus-4.7"

TIER_RANK = {"cheap": 1, "mid": 2, "top": 3}


# ---------- 路由规则 ----------
HARD_KEYWORDS = [
    "推理", "证明", "分析", "架构", "设计方案", "复杂", "为什么",
    "数学", "算法", "优化", "权衡", "深入",
    "prove", "reason", "analyze", "architect", "design", "complex",
    "tradeoff", "optimize", "algorithm", "derive", "explain why",
]

MEDIUM_KEYWORDS = [
    "代码", "实现", "写一个", "调试", "重构", "函数", "类",
    "code", "implement", "write a", "debug", "refactor", "function", "class",
    "fix", "bug",
]

SIMPLE_KEYWORDS = [
    "翻译", "总结", "改写", "润色", "摘要", "格式化", "列出",
    "translate", "summarize", "rewrite", "list", "format", "rephrase",
    "tldr",
]


@dataclass
class RouteDecision:
    tier: str
    model: str
    reasons: list[str]


def classify(prompt: str) -> RouteDecision:
    """规则路由：基于长度和关键词决定难度等级。"""
    text = prompt.lower()
    reasons = []

    hard_hits   = [k for k in HARD_KEYWORDS   if k.lower() in text]
    medium_hits = [k for k in MEDIUM_KEYWORDS if k.lower() in text]
    simple_hits = [k for k in SIMPLE_KEYWORDS if k.lower() in text]

    length = len(prompt)
    has_code_block = "```" in prompt
    multi_step = len(re.findall(r"[1-9][.、)]", prompt)) >= 3

    if hard_hits:
        tier = "top"
        reasons.append(f"命中困难关键词: {hard_hits[:3]}")
    elif has_code_block and length > 400:
        tier = "top"
        reasons.append("含长代码块 (>400 字符)，可能需要深度理解")
    elif medium_hits or has_code_block:
        tier = "mid"
        if medium_hits:
            reasons.append(f"命中代码/实现类关键词: {medium_hits[:3]}")
        if has_code_block:
            reasons.append("含代码块")
    elif simple_hits or length < 80:
        tier = "cheap"
        if simple_hits:
            reasons.append(f"命中简单任务关键词: {simple_hits[:3]}")
        if length < 80:
            reasons.append(f"prompt 较短 ({length} 字符)")
    else:
        tier = "mid"
        reasons.append("无明显特征，默认中等难度")

    if multi_step and tier != "top":
        tier = "top" if tier == "mid" else "mid"
        reasons.append("检测到多步骤任务 (≥3 个编号项)，升一档")

    model = TIER_DEFAULT[tier]
    reasons.append(f"选择 tier={tier} 中默认模型: {model}")
    return RouteDecision(tier=tier, model=model, reasons=reasons)


# ---------- 方案三: LLM Dispatcher (mock) ----------
# 真实实现里这里会调一个便宜模型（如 haiku-4.5）做分类。这里我们用一个
# 更精细的规则函数模拟它的输出 —— 带权重、否定检测、句式匹配。
# 同时把 dispatcher 自己消耗的 token 成本计入总账。

DISPATCHER_MODEL = "haiku-4.5"
SHORT_CIRCUIT_LEN = 18   # 短于此跳过 dispatcher（不值得调用）
DISPATCHER_SYS_TOKENS = 80   # 假装的 system prompt 开销

KEYWORD_WEIGHTS: dict[str, float] = {
    # hard 信号（正分大）
    "证明": 3.0, "权衡": 2.5, "架构": 2.5, "分析": 2.0, "为什么": 2.0,
    "推理": 2.0, "优化": 1.5, "复杂": 1.5,
    "prove": 3.0, "tradeoff": 2.5, "architect": 2.5, "analyze": 2.0,
    "reason": 2.0, "optimize": 1.5, "complex": 1.5, "derive": 2.5,
    # mid 信号
    "实现": 1.5, "重构": 2.0, "调试": 1.5, "代码": 1.5, "函数": 1.0,
    "code": 1.5, "implement": 1.5, "refactor": 2.0, "fix": 1.0, "bug": 1.0,
    "function": 1.0, "debug": 1.5, "write a": 1.0,
    # simple 信号（负分往下拉）
    "翻译": -2.0, "总结": -2.0, "改写": -1.5, "格式化": -1.5,
    "translate": -2.0, "summarize": -2.0, "rephrase": -1.5, "format": -1.5,
    # 语义下拉：暗示 "只要文字说明" 而非真要执行
    "思路": -1.5, "告诉我": -0.8, "解释一下": -0.8, "说一下": -0.8,
    "idea": -1.5, "in plain english": -1.5, "just describe": -1.0,
    "in words": -1.0, "tell me": -0.8,
}

NEGATIONS = ["不要", "别", "without", "no code", "don't"]


def _is_negated(text: str, keyword: str, window: int = 8) -> bool:
    """关键词前 window 个字符内是否有否定词。"""
    idx = text.find(keyword)
    if idx < 0:
        return False
    left = text[max(0, idx - window):idx]
    return any(neg in left for neg in NEGATIONS)


def dispatch_with_llm(prompt: str) -> tuple[RouteDecision, dict]:
    """
    Mock 一个 LLM dispatcher。返回 (RouteDecision, dispatcher_meta)。

    真实实现 (伪代码):
        resp = anthropic.messages.create(
            model="claude-haiku-4-5",
            system="把任务分成 cheap/mid/top 三档，输出 JSON",
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_json(resp), {"cost": resp.usage.cost, ...}
    """
    # ---- 短路：太短的 prompt 不值得调 dispatcher ----
    if len(prompt) < SHORT_CIRCUIT_LEN:
        d = classify(prompt)
        d.reasons.insert(0,
            f"短路: prompt < {SHORT_CIRCUIT_LEN} 字符，跳过 dispatcher，"
            f"回落到规则路由")
        return d, {"called": False, "cost": 0.0, "tokens": (0, 0)}

    text = prompt.lower()
    score = 0.0
    matched: list[str] = []

    # ---- 加权关键词 + 否定检测 ----
    for kw, w in KEYWORD_WEIGHTS.items():
        if kw in text:
            if _is_negated(text, kw):
                matched.append(f"{kw}({w:+.1f}, 被否定→丢弃)")
                continue
            score += w
            matched.append(f"{kw}({w:+.1f})")

    # ---- 句式模式 ----
    if re.search(r"为什么.*[？?]", prompt):
        score += 1.5
        matched.append("句式: '为什么...?' (+1.5)")
    if re.search(r"\bwhy\b.*\?", text):
        score += 1.5
        matched.append("pattern: 'why...?' (+1.5)")
    if re.match(r"^\s*翻译[:：]", prompt):
        score = min(score, -2.0)
        matched.append("句式: '翻译:' 开头 → 强制 cheap")
    if re.match(r"^\s*translate\s*[:：]", text):
        score = min(score, -2.0)
        matched.append("pattern: 'translate:' prefix → force cheap")
    if "```" in prompt and len(prompt) > 400:
        score += 2.0
        matched.append("长代码块 (+2.0)")

    # ---- 分档 ----
    if score >= 4.5:
        tier = "top"
    elif score >= 1.0:
        tier = "mid"
    else:
        tier = "cheap"

    # ---- 计算 dispatcher 自己的成本 ----
    disp_in  = DISPATCHER_SYS_TOKENS + max(1, len(prompt) // 4)
    disp_out = 30   # JSON 输出约 30 token
    disp_cost = cost(DISPATCHER_MODEL, disp_in, disp_out)

    reasons = [
        f"LLM dispatcher ({DISPATCHER_MODEL}) 输出: score={score:+.1f} → tier={tier}",
        f"命中信号: {matched[:6] if matched else ['(无)']}",
        f"选择模型: {TIER_DEFAULT[tier]}",
    ]
    decision = RouteDecision(tier=tier, model=TIER_DEFAULT[tier], reasons=reasons)
    return decision, {"called": True, "cost": disp_cost, "tokens": (disp_in, disp_out)}


# ---------- Mock 调用 & 成本 ----------
def mock_call(model: str, prompt: str) -> tuple[str, int, int]:
    """假装调用 LLM，返回 (response, input_tokens, output_tokens)。"""
    in_tokens = max(1, len(prompt) // 4)
    out_tokens = int(in_tokens * 1.5)
    response = f"[{model} 的 mock 回复] 针对「{prompt[:30]}...」"
    return response, in_tokens, out_tokens


def cost(model: str, in_tokens: int, out_tokens: int) -> float:
    m = MODELS[model]
    return (in_tokens * m.price_in + out_tokens * m.price_out) / 1_000_000


# ---------- 用户体验打分 (mock) ----------
def score_quality(model_tier: str, task_tier: str) -> int:
    """
    Mock 用户体验分 (1-10):
      模型能力 ≥ 任务难度 → 高分 (9-10)
      模型能力 < 任务难度 → 明显下降 (3-7)
    用 tier 之间的差距换算。
    """
    diff = TIER_RANK[model_tier] - TIER_RANK[task_tier]
    return {2: 10, 1: 10, 0: 9, -1: 6, -2: 3}[diff]


# ---------- 单条 prompt 路由 ----------
def route_and_run(prompt: str, mode: str = "rule") -> dict:
    """mode: 'rule' (方案一) or 'llm' (方案三, 带 dispatcher)"""
    if mode == "llm":
        decision, disp_meta = dispatch_with_llm(prompt)
    else:
        decision = classify(prompt)
        disp_meta = {"called": False, "cost": 0.0, "tokens": (0, 0)}

    response, in_tok, out_tok = mock_call(decision.model, prompt)
    exec_cost = cost(decision.model, in_tok, out_tok)
    actual_cost   = exec_cost + disp_meta["cost"]
    baseline_cost = cost(BASELINE_MODEL, in_tok, out_tok)
    saved = baseline_cost - actual_cost
    saved_pct = (saved / baseline_cost * 100) if baseline_cost else 0
    chosen_tier = MODELS[decision.model].tier
    quality = score_quality(chosen_tier, decision.tier)
    baseline_quality = score_quality(MODELS[BASELINE_MODEL].tier, decision.tier)

    return {
        "prompt": prompt,
        "mode": mode,
        "decision": decision,
        "response": response,
        "tokens": (in_tok, out_tok),
        "exec_cost": exec_cost,
        "dispatcher_cost": disp_meta["cost"],
        "dispatcher_called": disp_meta["called"],
        "actual_cost": actual_cost,
        "baseline_cost": baseline_cost,
        "saved": saved,
        "saved_pct": saved_pct,
        "quality": quality,
        "baseline_quality": baseline_quality,
    }


def print_result(r: dict) -> None:
    d: RouteDecision = r["decision"]
    in_tok, out_tok = r["tokens"]
    print("─" * 70)
    print(f"PROMPT : {r['prompt']}")
    print(f"MODE   : {r['mode']}   →   TIER: {d.tier}   MODEL: {d.model}")
    print("REASON :")
    for line in d.reasons:
        print(f"   • {line}")
    print(f"TOKENS : in={in_tok}  out={out_tok}")
    if r["dispatcher_called"]:
        print(f"COST   : ${r['actual_cost']:.6f} "
              f"(exec ${r['exec_cost']:.6f} + dispatcher ${r['dispatcher_cost']:.6f})")
    else:
        print(f"COST   : ${r['actual_cost']:.6f}")
    print(f"         baseline {BASELINE_MODEL}: ${r['baseline_cost']:.6f}, "
          f"省 ${r['saved']:.6f} / {r['saved_pct']:.1f}%")
    print(f"QUALITY: {r['quality']}/10   "
          f"(baseline {BASELINE_MODEL}: {r['baseline_quality']}/10)")
    print(f"REPLY  : {r['response']}")


# ---------- 多 agent 协作任务 ----------
@dataclass
class Subtask:
    """协作 task 中的一个子步骤。true_tier 是"真实难度"，用来打质量分。"""
    name: str
    prompt: str
    true_tier: str    # cheap / mid / top — 任务客观难度

@dataclass
class Task:
    name: str
    subtasks: list[Subtask] = field(default_factory=list)


# 四种策略：全便宜 / 规则路由 / LLM 调度 / 全顶配
def run_subtask(sub: Subtask, strategy: str) -> dict:
    disp_cost = 0.0
    if strategy == "routed":
        decision = classify(sub.prompt)
        model, reasons = decision.model, decision.reasons
    elif strategy == "llm-dispatch":
        decision, meta = dispatch_with_llm(sub.prompt)
        model, reasons = decision.model, decision.reasons
        disp_cost = meta["cost"]
    elif strategy == "all-cheap":
        model = TIER_DEFAULT["cheap"]
        reasons = ["策略=all-cheap，强制用便宜模型"]
    elif strategy == "all-top":
        model = BASELINE_MODEL
        reasons = ["策略=all-top，全部用顶配模型"]
    else:
        raise ValueError(strategy)

    _, in_tok, out_tok = mock_call(model, sub.prompt)
    c = cost(model, in_tok, out_tok) + disp_cost
    q = score_quality(MODELS[model].tier, sub.true_tier)
    return {
        "subtask": sub,
        "model": model,
        "reasons": reasons,
        "cost": c,
        "dispatcher_cost": disp_cost,
        "quality": q,
        "tokens": (in_tok, out_tok),
    }


def run_task(task: Task, strategy: str) -> dict:
    results = [run_subtask(s, strategy) for s in task.subtasks]
    total_cost = sum(r["cost"] for r in results)
    avg_q = sum(r["quality"] for r in results) / len(results)
    return {"task": task, "strategy": strategy, "results": results,
            "total_cost": total_cost, "avg_quality": avg_q}


def print_task_run(run: dict) -> None:
    print(f"\n┌── TASK: {run['task'].name}   [strategy={run['strategy']}]")
    for r in run["results"]:
        sub = r["subtask"]
        flag = "" if MODELS[r["model"]].tier == sub.true_tier \
               else (" ⬆over-spec" if TIER_RANK[MODELS[r["model"]].tier] > TIER_RANK[sub.true_tier]
                     else " ⚠under-spec")
        print(f"│  • [{sub.true_tier:<5}] {sub.name}")
        print(f"│        → {r['model']}{flag}  cost=${r['cost']:.6f}  quality={r['quality']}/10")
    print(f"└── TOTAL  cost=${run['total_cost']:.6f}   "
          f"avg quality={run['avg_quality']:.1f}/10")


def compare_strategies(task: Task) -> None:
    print("\n" + "=" * 70)
    print(f"### Multi-Agent Task: {task.name}")
    print("=" * 70)

    strategies = ["all-cheap", "routed", "llm-dispatch", "all-top"]
    runs = {s: run_task(task, s) for s in strategies}
    for r in runs.values():
        print_task_run(r)

    print("\n  ┃ 横向对比 (cost / avg quality):")
    for s in strategies:
        r = runs[s]
        extra = ""
        if s == "llm-dispatch":
            disp = sum(x["dispatcher_cost"] for x in r["results"])
            extra = f"  [dispatcher 自身 ${disp:.6f}]"
        print(f"  ┃   {s:<13} ${r['total_cost']:.6f}   "
              f"{r['avg_quality']:.1f}/10{extra}")


# ---------- Demo 数据 ----------
DEMO_PROMPTS = [
    "Translate: Hello world",
    "Write a Python function to deduplicate a list while preserving order",
    "Analyze the tradeoffs of the CAP theorem in distributed databases and prove why all three properties cannot be satisfied simultaneously",
    "Summarize this: the weather is nice today",
    "fix this bug: ```python\ndef f(x): return x/0\n```",
]

# 对抗性 prompt: rule 会翻车, LLM dispatcher 应该处理得更好
DISPATCHER_DEMO_PROMPTS = [
    # rule 命中 "algorithm" 升 top; dispatcher 检测到 "don't" 否定 + "idea" 负分 → 应判 cheap
    "Don't give me code — just describe the dedup algorithm idea in plain English",
    # rule 命中 "analyze" 升 top; dispatcher 看 "translate"(-2) + "analyze"(+2) = 0 → cheap
    "Translate this and analyze the author's tone: The weather is unexpectedly nice today.",
    # rule 和 dispatcher 都应判 top (一致的难任务)
    "Why does this code have a race condition? Please analyze in depth.",
    # 长但简单 — rule 因长度不会降档; dispatcher 看 "summarize" 应判 cheap
    "Summarize the meeting notes below into three bullets: today we discussed next week's "
    "release plan. Frontend ships UI redesign by Monday, backend API by Tuesday, "
    "QA runs regression on Wednesday, release on Thursday.",
]

DEMO_TASKS = [
    Task("News aggregator bot", [
        Subtask("Fetch RSS feed and parse titles",
                "List all entries from the RSS feed with title and publish time",   "cheap"),
        Subtask("Write a dedup function",
                "Write a Python function to deduplicate the news list by URL while preserving order",  "mid"),
        Subtask("Summarize each item in 50 words",
                "Summarize this news article in under 50 English words",            "cheap"),
        Subtask("Design push strategy & rate limiting",
                "Analyze the tradeoffs of different push frequencies on user fatigue and design an optimal push strategy",  "top"),
        Subtask("Generate markdown daily digest",
                "Format the following news items into a markdown list with hyperlinks",  "cheap"),
    ]),
    Task("Code review of a concurrency module", [
        Subtask("List all function signatures",
                "List the signatures (name + params) of every function in this code",  "cheap"),
        Subtask("Per-function implementation check",
                "Implement unit tests for each function in this code",              "mid"),
        Subtask("Deep concurrency-safety analysis",
                "Deeply analyze the concurrency safety of this code and prove why a race condition occurs",  "top"),
        Subtask("Propose refactoring plan",
                "Propose a refactoring plan for the thread-safety issues and analyze the tradeoffs of multiple implementations",  "top"),
    ]),
]


# ---------- 主流程 ----------
def _print_compare_table(prompts: list[str], header: str) -> None:
    print("\n" + "=" * 70)
    print(f"### {header}")
    print("=" * 70)
    print(f"{'PROMPT':<46}  {'rule':<22}  {'llm-dispatch':<22}")
    print("-" * 96)
    for p in prompts:
        r1 = route_and_run(p, mode="rule")
        r2 = route_and_run(p, mode="llm")
        flag1 = "✅" if r1["quality"] >= 9 else "⚠"
        flag2 = "✅" if r2["quality"] >= 9 else "⚠"
        col1 = f"{r1['decision'].model:<14} q{r1['quality']}/10 {flag1}"
        col2 = f"{r2['decision'].model:<14} q{r2['quality']}/10 {flag2}"
        short = p[:43] + "..." if len(p) > 46 else p
        print(f"{short:<46}  {col1:<22}  {col2:<22}")


def main() -> None:
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print("--- mode=rule ---")
        print_result(route_and_run(prompt, mode="rule"))
        print("\n--- mode=llm ---")
        print_result(route_and_run(prompt, mode="llm"))
        return

    # 1. 普通 prompt 上两种 mode 通常会一致 —— 验证 dispatcher 不会"更傻"
    _print_compare_table(DEMO_PROMPTS,
                         "单条 prompt: rule vs llm-dispatch")
    # 2. 对抗性 prompt —— dispatcher 应该明显优于 rule
    _print_compare_table(DISPATCHER_DEMO_PROMPTS,
                         "对抗性 prompt: dispatcher 的优势场景")

    # 3. 多 agent 任务：4 策略横向对比
    for t in DEMO_TASKS:
        compare_strategies(t)


if __name__ == "__main__":
    main()
