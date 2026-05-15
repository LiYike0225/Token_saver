"""
LLM Router Demo — 根据任务难度把请求分发到合适的模型，省 token 成本。

用法:
    python router.py                  # 跑内置 demo
    python router.py "你的问题..."     # 路由单条 prompt
"""

import re
import sys
from dataclasses import dataclass


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

# 每个 tier 默认选哪个模型（同 tier 内挑最便宜的）
TIER_DEFAULT = {
    "cheap": "gpt-4o-mini",
    "mid":   "deepseek-chat" if False else "sonnet-4.6",  # 也可换 gpt-4o
    "top":   "opus-4.7",
}

# 对比基线：如果不用路由，全部丢给 top 模型的话
BASELINE_MODEL = "opus-4.7"


# ---------- 路由规则 ----------
HARD_KEYWORDS = [
    # 中文
    "推理", "证明", "分析", "架构", "设计方案", "复杂", "为什么",
    "数学", "算法", "优化", "权衡", "深入",
    # English
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

    # 用字符数粗估长度（中英文混合时不区分）
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


# ---------- Mock 调用 ----------
def mock_call(model: str, prompt: str) -> tuple[str, int, int]:
    """假装调用 LLM，返回 (response, input_tokens, output_tokens)。
    token 数用 字符数/4 粗估，output 假设是 input 的 1.5 倍。"""
    in_tokens = max(1, len(prompt) // 4)
    out_tokens = int(in_tokens * 1.5)
    response = f"[{model} 的 mock 回复] 针对「{prompt[:30]}...」的回答..."
    return response, in_tokens, out_tokens


def cost(model: str, in_tokens: int, out_tokens: int) -> float:
    m = MODELS[model]
    return (in_tokens * m.price_in + out_tokens * m.price_out) / 1_000_000


# ---------- 主流程 ----------
def route_and_run(prompt: str) -> dict:
    decision = classify(prompt)
    response, in_tok, out_tok = mock_call(decision.model, prompt)
    actual_cost   = cost(decision.model,   in_tok, out_tok)
    baseline_cost = cost(BASELINE_MODEL,   in_tok, out_tok)
    saved = baseline_cost - actual_cost
    saved_pct = (saved / baseline_cost * 100) if baseline_cost else 0

    return {
        "prompt": prompt,
        "decision": decision,
        "response": response,
        "tokens": (in_tok, out_tok),
        "actual_cost": actual_cost,
        "baseline_cost": baseline_cost,
        "saved": saved,
        "saved_pct": saved_pct,
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
    print(f"REPLY  : {r['response']}")


DEMO_PROMPTS = [
    "翻译: Hello world",
    "帮我写一个 Python 函数，把列表去重并保持顺序",
    "请分析一下 CAP 定理在分布式数据库设计中的权衡，并证明为什么不可能同时满足三者",
    "总结这段话: 今天天气不错",
    "1. 读取 CSV  2. 清洗空值  3. 按月份聚合  4. 画图  帮我写完整代码",
    "fix this bug: ```python\ndef f(x): return x/0\n```",
]


def main() -> None:
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print_result(route_and_run(prompt))
        return

    print("=== LLM Router Demo (mock) ===\n")
    total_actual = total_baseline = 0.0
    for p in DEMO_PROMPTS:
        r = route_and_run(p)
        print_result(r)
        total_actual   += r["actual_cost"]
        total_baseline += r["baseline_cost"]

    print("─" * 70)
    print(f"SUMMARY: 共 {len(DEMO_PROMPTS)} 条请求")
    print(f"  路由总成本   : ${total_actual:.6f}")
    print(f"  全跑 {BASELINE_MODEL} : ${total_baseline:.6f}")
    print(f"  节省           : ${total_baseline - total_actual:.6f} "
          f"({(1 - total_actual/total_baseline)*100:.1f}%)")


if __name__ == "__main__":
    main()
