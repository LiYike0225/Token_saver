# LLM Router Demo

一个极简的多模型路由器 demo，灵感来自 [Poe](https://poe.com/)：根据任务难度把请求分发到不同价位的 LLM，省 token 成本。

**这是一个 mock demo**，不实际调用任何 LLM API。

## 思路

不同 LLM 价格差距很大（Opus 比 GPT-4o-mini 贵 ~100×），但很多日常任务（翻译、总结、格式化）便宜模型完全够用。路由器的目标：

> 自动判断任务难度 → 选最便宜且够用的模型 → 同等体验下省钱。

## 路由策略

实现了**两种路由模式**，可以横向对比：

### 模式 1：规则路由 (`mode=rule`，默认)

快 + 可解释，纯关键词+长度判定，不调任何模型：

| 触发条件 | 分档 | 默认模型 |
|---------|------|---------|
| 命中 "翻译 / 总结 / translate / summarize…" 或 prompt < 80 字符 | `cheap` | gpt-4o-mini |
| 命中 "代码 / 函数 / implement / fix…" 或含 ` ``` ` 代码块 | `mid` | sonnet-4.6 |
| 命中 "分析 / 证明 / 为什么 / reason / prove…" 或长代码块 | `top` | opus-4.7 |
| 检测到 ≥3 个编号步骤 (`1. 2. 3.`) | 自动升一档 | |

每次路由都会打印命中的具体规则，方便调试和理解。

### 模式 2：LLM Dispatcher (`mode=llm`)

让一个便宜模型 (haiku-4.5) 当"调度员"专门做难度分类，再分发给执行模型。
**本 demo 用一个更精细的规则函数模拟它的输出**（带权重 / 否定检测 / 句式匹配），同时把 dispatcher 自己消耗的 token 算进总成本。

```
prompt
  │
  ▼  ① dispatcher (haiku-4.5, ~$0.00005/次)
  │    输出: {"tier": "mid", "score": 1.5, "reason": "代码相关"}
  ▼
  ② 执行模型 (gpt-4o-mini / sonnet-4.6 / opus-4.7)
```

短路优化：prompt < 18 字符直接回落到规则路由，不调 dispatcher。

**dispatcher 比规则强在哪**：
- 否定词识别（"不要给我代码…" → 不会因为命中"代码"被错判 mid）
- 关键词冲突时按权重打分而非先命中先赢
- 句式模式 (`为什么...?` → top；`^翻译:` → 强制 cheap)

**dispatcher 不是免费午餐**：自身要花 token，**只有遇到歧义/对抗性 prompt 才回本**。简单清晰的 prompt 上，规则免费且同样准——见下面对比。

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

## 规则 vs Dispatcher 对抗性对比

跑 `python3 router.py` 后会先打印这张表（节选）：

```
PROMPT                                  rule              llm-dispatch
不要给我代码，只用文字告诉我去重算法的实现思路就好    opus-4.7   q9 ⚠   gpt-4o-mini  q9 ✅
翻译这段并分析作者的语气：The weather is...       opus-4.7   q9 ⚠   gpt-4o-mini  q9 ✅
为什么这段代码会出现 race condition？请深入分析     opus-4.7   q9 ✅   opus-4.7    q9 ✅
```

前两条 rule 误升到 opus（被"算法"/"分析"等关键词带偏），dispatcher 靠否定词和权重正确降到 cheap → 直接省 ~100×。

## 多 Agent 协作任务

一个复杂 task 通常由多个子步骤组成，每步难度不同。本 demo 内置两个示例任务（新闻聚合机器人 / 代码 review），每个子任务标注真实难度，对比 **4 种策略**：

| 策略 | 思路 | 适用 |
|------|------|------|
| `all-cheap` | 全用便宜模型 | 省钱激进，但难任务质量会崩 |
| `routed` | 规则路由 | 平衡，0 路由开销 ✅ |
| `llm-dispatch` | LLM 调度员 | 同质量但多花 dispatcher 钱（清晰 prompt 不划算） |
| `all-top` | 全用顶配 | 质量满分但浪费 |

跑完会打印对比，例如新闻聚合任务：

```
all-cheap     $0.000034   7.2/10   ← 难任务崩了
routed        $0.001078   9.0/10   ← 规则就够用
llm-dispatch  $0.002262   9.0/10   [dispatcher 自身 $0.001184，纯开销]
all-top       $0.004185   9.8/10
```

**结论**：清晰任务上 dispatcher 是浪费；只有歧义/对抗 prompt 上 dispatcher 才值得调。生产里通常加更激进的短路（长度、白名单关键词）来减少 dispatcher 调用次数。

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
