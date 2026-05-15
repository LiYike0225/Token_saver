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
def route_and_run(prompt: str) -> dict:
    decision = classify(prompt)
    response, in_tok, out_tok = mock_call(decision.model, prompt)
    actual_cost   = cost(decision.model, in_tok, out_tok)
    baseline_cost = cost(BASELINE_MODEL, in_tok, out_tok)
    saved = baseline_cost - actual_cost
    saved_pct = (saved / baseline_cost * 100) if baseline_cost else 0
    chosen_tier = MODELS[decision.model].tier
    quality = score_quality(chosen_tier, decision.tier)
    baseline_quality = score_quality(MODELS[BASELINE_MODEL].tier, decision.tier)

    return {
        "prompt": prompt,
        "decision": decision,
        "response": response,
        "tokens": (in_tok, out_tok),
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
    print(f"TIER   : {d.tier}   →   MODEL: {d.model}")
    print("REASON :")
    for line in d.reasons:
        print(f"   • {line}")
    print(f"TOKENS : in={in_tok}  out={out_tok}")
    print(f"COST   : ${r['actual_cost']:.6f}   "
          f"(baseline {BASELINE_MODEL}: ${r['baseline_cost']:.6f}, "
          f"省 ${r['saved']:.6f} / {r['saved_pct']:.1f}%)")
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


# 三种策略：路由 / 全用便宜的 / 全用最贵的
def run_subtask(sub: Subtask, strategy: str) -> dict:
    if strategy == "routed":
        decision = classify(sub.prompt)
        model = decision.model
        reasons = decision.reasons
    elif strategy == "all-cheap":
        model = TIER_DEFAULT["cheap"]
        reasons = ["策略=all-cheap，强制用便宜模型"]
    elif strategy == "all-top":
        model = BASELINE_MODEL
        reasons = ["策略=all-top，全部用顶配模型"]
    else:
        raise ValueError(strategy)

    _, in_tok, out_tok = mock_call(model, sub.prompt)
    c = cost(model, in_tok, out_tok)
    q = score_quality(MODELS[model].tier, sub.true_tier)
    return {
        "subtask": sub,
        "model": model,
        "reasons": reasons,
        "cost": c,
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

    runs = {s: run_task(task, s) for s in ["all-cheap", "routed", "all-top"]}
    for r in runs.values():
        print_task_run(r)

    baseline = runs["all-top"]
    routed   = runs["routed"]
    cheap    = runs["all-cheap"]
    saved = baseline["total_cost"] - routed["total_cost"]
    saved_pct = saved / baseline["total_cost"] * 100
    q_drop = baseline["avg_quality"] - routed["avg_quality"]
    print("\n  ┃ 路由 vs 全顶配 (baseline):")
    print(f"  ┃   省钱     : ${saved:.6f}  ({saved_pct:.1f}%)")
    print(f"  ┃   质量损失 : {q_drop:.1f}/10  "
          f"({routed['avg_quality']:.1f} vs {baseline['avg_quality']:.1f})")
    print("  ┃ 路由 vs 全便宜 (省钱激进):")
    print(f"  ┃   多花     : ${routed['total_cost'] - cheap['total_cost']:.6f}")
    print(f"  ┃   换来质量 : +{routed['avg_quality'] - cheap['avg_quality']:.1f}/10")


# ---------- Demo 数据 ----------
DEMO_PROMPTS = [
    "翻译: Hello world",
    "帮我写一个 Python 函数，把列表去重并保持顺序",
    "请分析一下 CAP 定理在分布式数据库设计中的权衡，并证明为什么不可能同时满足三者",
    "总结这段话: 今天天气不错",
    "fix this bug: ```python\ndef f(x): return x/0\n```",
]

DEMO_TASKS = [
    Task("新闻聚合机器人", [
        Subtask("抓取 RSS feed 并解析标题",
                "请帮我列出 RSS feed 里所有条目的标题",                 "cheap"),
        Subtask("写一个去重函数",
                "写一个 Python 函数对新闻列表按 URL 去重",              "mid"),
        Subtask("逐条生成 50 字摘要",
                "帮我总结这条新闻为 50 字",                            "cheap"),
        Subtask("设计推送策略与频控",
                "请分析不同推送频率的权衡，设计一个最优推送策略",         "top"),
        Subtask("生成 markdown 日报",
                "把以下条目格式化为 markdown 列表",                    "cheap"),
    ]),
    Task("Code Review 并发模块", [
        Subtask("列出所有函数签名",
                "列出这段代码的所有函数",                              "cheap"),
        Subtask("逐函数实现检查",
                "实现一下每个函数的单元测试",                          "mid"),
        Subtask("并发安全性深度分析",
                "请分析这段代码的并发安全性，证明为什么会有 race condition",  "top"),
        Subtask("给出重构方案",
                "请给出重构方案并分析权衡",                            "top"),
    ]),
]


# ---------- 主流程 ----------
def main() -> None:
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print_result(route_and_run(prompt))
        return

    print("=" * 70)
    print("### 单条 prompt 路由")
    print("=" * 70)
    total_actual = total_baseline = 0.0
    total_q = total_baseline_q = 0.0
    for p in DEMO_PROMPTS:
        r = route_and_run(p)
        print_result(r)
        total_actual     += r["actual_cost"]
        total_baseline   += r["baseline_cost"]
        total_q          += r["quality"]
        total_baseline_q += r["baseline_quality"]
    n = len(DEMO_PROMPTS)
    print("─" * 70)
    print(f"SUMMARY: 共 {n} 条")
    print(f"  路由总成本   : ${total_actual:.6f}")
    print(f"  全跑 {BASELINE_MODEL} : ${total_baseline:.6f}")
    print(f"  节省          : ${total_baseline - total_actual:.6f} "
          f"({(1 - total_actual/total_baseline)*100:.1f}%)")
    print(f"  平均质量      : {total_q/n:.1f}/10  "
          f"(baseline: {total_baseline_q/n:.1f}/10)")

    for t in DEMO_TASKS:
        compare_strategies(t)


if __name__ == "__main__":
    main()
