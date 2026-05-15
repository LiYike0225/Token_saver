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
```

内置 demo 跑完会输出汇总：6 条混合请求相比"全部丢给 opus-4.7"省了约 **45%**。

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
