# LLM Router Demo

一个极简的多模型路由器 demo，灵感来自 [Poe](https://poe.com/)：根据任务难度把请求分发到不同价位的 LLM，省 token 成本。

**这是一个 mock demo**，不实际调用任何 LLM API。

## 思路

不同 LLM 价格差距很大（Opus 比 GPT-4o-mini 贵 ~100×），但很多日常任务（翻译、总结、格式化）便宜模型完全够用。路由器的目标：

> 自动判断任务难度 → 选最便宜且够用的模型 → 同等体验下省钱。

## 路由策略

走"快 + 可解释"路线，纯规则，不调用任何分类模型：

| 触发条件 | 分档 | 默认模型 |
|---------|------|---------|
| 命中关键词 "翻译 / 总结 / translate / summarize…" 或 prompt < 80 字符 | `cheap` | gpt-4o-mini |
| 命中 "代码 / 函数 / implement / fix…" 或含 ` ``` ` 代码块 | `mid` | sonnet-4.6 |
| 命中 "分析 / 证明 / 为什么 / reason / prove…" 或长代码块 | `top` | opus-4.7 |
| 检测到 ≥3 个编号步骤 (`1. 2. 3.`) | 自动升一档 | |

每次路由都会打印命中的具体规则，方便调试和理解。

## 用法

```bash
# 跑内置 6 条 demo prompt
python3 router.py

# 路由单条 prompt
python3 router.py "帮我写一个 Python 函数把列表去重"
```

无依赖，纯 Python 标准库。

## 输出示例

```
PROMPT : 帮我写一个 Python 函数，把列表去重并保持顺序
TIER   : mid   →   MODEL: sonnet-4.6
REASON :
   • 命中代码/实现类关键词: ['写一个', '函数']
   • 选择 tier=mid 中默认模型: sonnet-4.6
TOKENS : in=6  out=9
COST   : $0.000153   (baseline opus-4.7: $0.000765, 省 $0.000612 / 80.0%)
QUALITY: 9/10   (baseline opus-4.7: 9/10)
```

## 用户体验质量分 (mock)

每次路由会算一个质量分 (1–10)，用来对照"省了钱有没有掉体验"。规则：

| 模型档位 vs 任务难度 | 质量分 |
|----------------------|------:|
| 模型 = 任务难度 (刚好匹配) | 9 |
| 模型 > 任务难度 (over-spec) | 10 |
| 模型 < 任务难度 1 档 | 6 |
| 模型 < 任务难度 2 档 | 3 |

## 多 Agent 协作任务

一个复杂 task 通常由多个子步骤组成，每步难度不同。本 demo 内置两个示例任务（新闻聚合机器人 / 代码 review），每个子任务标注真实难度，对比三种策略：

| 策略 | 思路 | 适用 |
|------|------|------|
| `all-cheap` | 全用便宜模型 | 省钱激进，但难任务质量会崩 |
| `routed` | 按难度路由 | 平衡 ✅ |
| `all-top` | 全用顶配 | 质量满分但浪费 |

跑完会打印对比，例如 Code Review 任务：

```
all-cheap : $0.000017   quality 5.2/10   ← 难任务崩了
routed    : $0.001575   quality 9.2/10   ← 平衡
all-top   : $0.002055   quality 9.5/10   ← 多花 23% 只换 0.3 分
```

## 模型池 (mock 价格，参考 2026 市价)

| Model | Tier | Input $/1M | Output $/1M |
|-------|------|-----------:|------------:|
| gpt-4o-mini    | cheap | 0.15  | 0.60  |
| deepseek-chat  | cheap | 0.27  | 1.10  |
| haiku-4.5      | cheap | 1.00  | 5.00  |
| sonnet-4.6     | mid   | 3.00  | 15.00 |
| gpt-4o         | mid   | 2.50  | 10.00 |
| opus-4.7       | top   | 15.00 | 75.00 |

## 接入真实 API

`router.py` 里只需改两处：

1. `mock_call()` → 替换为 `openai` / `anthropic` SDK 的真实调用
2. `MODELS` 里价格表保留，token 数从 API response 里拿真实值

## License

MIT
