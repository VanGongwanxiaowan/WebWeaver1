
我先把 `docs/paper` 里的几篇文档读一遍（工作流程、评判标准、案例研究等），对照现在的 planner/writer Prompt 和 orchestrator 实现，检查有哪些论文工作流或评价维度还没在 Prompt 里体现，再给出需要补充或修改的点（必要的话直接帮你改代码）。

[7 tools called]

### 总体结论

**现在代码里的业务流程，已经基本对齐你论文里的核心方法论**：  
- 双智能体（planner + writer）、  
- ReAct 循环（思考-调用工具-观察-写）、  
- Tavily 检索 + URL 过滤 + 摘要 + evidence 抽取的 `memory bank`、  
- “搜索规划 → 大纲优化 → 分节写作”的三阶段流程，  
这些在 `docs/paper` 和当前实现里是一致的，没有“少一整块流程”的大问题。

### 和论文对照后，主要还没完全“显式写进 Prompt / 逻辑”的点

结合你给的 @paper 文档，我看到有几类东西**在论文中强调，但在 Prompt / 约束里还可以再补得更细**：

- **1）Outline 评估维度没完全显式暴露给 planner**  
  - 论文里的 `judgementcriteria.md` + `PromptOutlineJudgement.md` 明确了 6 个维度：  
    **Instruction following / Depth / Balance / Breadth / Support / Insightfulness**。  
  - 当前 `PLANNER_SYSTEM_PROMPT` 里重点强调了：深度（Depth）、证据支撑（Support）、洞见性（Insightfulness），  
    但 **Balance（多视角、公平性）** 和 **Breadth（多维度覆盖：技术、法律、伦理、经济、应用等）** 提得相对弱。  
  - 可以再加一小段中文说明，让 planner 在写大纲时：  
    - 主动为“争议点、风险、局限性”预留 **对立观点 / 反方证据 / trade-off 小节**；  
    - 在应用、安全/伦理、监管合规、技术细节、实验评估、落地路径等维度上 **检查是否都有覆盖**。

- **2）论文中的 ReAct 轨迹示例里有 `<think>` / `<tool_response>`，目前 Prompt 里不要求显式输出**  
  - `案例研究.md` 里的 B.2 / B.3 轨迹有：  
    `<think>…</think> -> <tool_call>…</tool_call> -> <tool_response>…</tool_response> -> <write_outline>/<write>…`。  
  - 当前实现的设计（包括你原来的英文 Prompt）是：  
    - **禁止输出 `<think>` 和自然语言思考，只允许三种标签**：  
      - planner：`<tool_call> / <write_outline> / <terminate>`  
      - writer：`<tool_call> / <write> / <terminate>`  
    - `<tool_response>` 是由系统（Python 代码）注入，不由 LLM 产生。  
  - 这算是**工程化的“精简版 ReAct”**，和论文的完整日志格式稍有差异，但逻辑是一致的，并不算“缺逻辑”。  
  - 如果你想更贴论文，可以在将来做 SFT / 训练数据时，用论文里的轨迹格式；**推理阶段这套精简协议是合理的**。

- **3）Agentic finetuning / WebWeaver‑3k 在当前项目里还只是“论文设想”，没有训练代码**  
  - `4-6智能体微调sft和相关工作结论.md` 里详细讲了 WebWeaver‑3k、SFT 流程、性能提升。  
  - 当前仓库只包含：  
    - 运行时框架（双 agent、工具、Tavily 搜索等），  
    - 评估逻辑（outline_judge 等），  
    - **没有包含生成 SFT 数据 / 训练 Qwen 的脚本**。  
  - 这属于**训练阶段的工程**，不是“推理业务逻辑”，严格说不是“缺业务逻辑”，而是“训练 pipeline 尚未开源”。  
  - 如果你后续真要做“按论文那样微调智谱本地模型”，需要额外一套：  
    - 轨迹导出 → 数据清洗 → SFT 训练脚本，这在当前项目中还没有。

- **4）评估器 Prompt 是英文的，可以考虑也改成中文版本，但逻辑是齐的**  
  - `PromptOutlineJudgement.md` 已经和 `judgementcriteria.md` 严格对齐，用来生成如你 artifacts 里 `outline_judgement.json` 的评分。  
  - 目前它是英文说明 + JSON 输出约束，**逻辑上和论文一致**，只是语言没本地化。  
  - 如果你希望整个链条都中文，可以再做一版“中文说明 + 保持 JSON 输出不变”的 Judger Prompt，这属于“体验增强”，不是缺逻辑。

### 小结：项目是否有没补上的“业务逻辑”？

- **核心业务逻辑（双智能体、动态搜索-大纲循环、记忆库、分节检索写作、Tavily 检索、引用驱动写作）已经和论文完全对得上。**  
- 论文中更细的几项：  
  - 6 维度评估里的 **Balance / Breadth** 可以在 planner Prompt 里再“说得更死一点”；  
  - ReAct 完整轨迹中的 `<think>` / `<tool_response>` 目前是工程化精简版，不算缺逻辑；  
  - Agentic finetuning / WebWeaver‑3k 是训练部分，目前仓库里还没实现；  
  - Judger Prompt 目前是英文描述，可以按需要改为中文。

如果你愿意，我可以下一步帮你：  
- **再给 planner 的系统 Prompt 加上一小段，专门约束 Balance / Breadth 两个维度**；  
- 同时给一个“中文版 Outline Judger Prompt”，保证评估标准与 `judgementcriteria.md` 严格一致。

## 0. 项目目标与边界

### 0.1 目标
实现一个 **WebWeaver 双智能体框架**，面向 Open-Ended Deep Research (OEDR) 任务：  
用户给出一个开放式研究问题（Query），系统通过“规划器 Planner + 写作者 Writer”的协作，在网络规模信息中完成证据搜集、结构化大纲生成与迭代优化、基于证据的分段写作，最终输出**结构严谨、覆盖全面、引用可追溯、尽量低幻觉**的长报告。

### 0.2 关键成功指标（与 docs 对齐）
来自 [docs/judgementcriteria.md](cci:7://file:///Users/gongfan/WebWeaver1/docs/judgementcriteria.md:0:0-0:0) 的 outline/报告质量维度（0-10 打分）必须能被“架构与输出格式”直接支持：
- **Instruction following**：严格遵循用户要求（范围、格式、层级结构、必须包含的章节等）。
- **Depth**：大纲/报告必须有足够细粒度子点、分析路径、假设/不确定性、方法、指标等。
- **Balance**：体现多视角/反例/限制与权衡。
- **Breadth**：覆盖多个相关维度（历史、监管、市场、技术、伦理、风险、落地路径等，按任务适配）。
- **Support**：**必须提供 URL 或可追踪来源**；缺失来源则该项必须为 0。  
  高分要求：事实/数据/案例都能定位到可信来源（作者/机构/日期/URL），避免“studies show”。
- **Insightfulness**：不仅是模板，要有非显而易见的结构、可执行建议与衡量方式、建议合适图表/框架。

### 0.3 边界与非目标（第一阶段）
- 第一阶段优先实现 **框架闭环**（Planner 循环 + Evidence Memory + Writer 分段写作 + 引用检索写作），先保证可跑通。
- 不强制实现训练/SFT（`docs/4-6...` 只是背景）。后续可追加数据生成与训练脚本。
- 不强制实现复杂前端/UI。可先提供 CLI 或最小 API（如 FastAPI SSE）用于流式输出。

---

## 1. 总体架构概览

### 1.1 双智能体分工（与 `docs/3.方法.md` 对齐）
- **Planner（规划器）**：动态研究循环  
  在每轮中选择 `search` / `write_outline` / `terminate` 三种动作之一：
  1. `search`：提出若干搜索 query -> 搜索引擎返回候选 -> LLM 过滤相关 URL -> 抓取/解析页面 -> 生成 Summary + Extract Evidence -> 写入 Memory Bank（带证据 ID）。
  2. `write_outline`：基于当前已收集证据与摘要，生成/优化大纲；大纲必须包含对 Memory Bank 的引用（`<citation>id_x</citation>` 或等价结构）。
  3. `terminate`：当大纲足够完整且证据支撑充分，结束规划阶段。
- **Writer（写作者）**：基于大纲的分层检索写作  
  对大纲的每个 section（建议按 H2/H3 级别）：
  1. 读取该 section 关联的 citation IDs
  2. 从 Memory Bank 定向检索对应证据（而不是把全部证据塞上下文）
  3. 生成该 section 文本（严格来源支撑，必要时注明不确定性）
  4. 最终串成完整报告

### 1.2 核心设计原则
- **行动可解释**：遵循 `docs/案例研究.md` 的轨迹格式：`<think> / <tool_call> / <tool_response> / <write_outline> / <write> / <terminate>`。
- **证据与写作解耦**：Planner 负责“搜集与组织证据 + 大纲引用映射”，Writer 只拿“当前 section 需要的证据”。
- **减少长上下文损失**：写作阶段禁止把全部 evidence dump 进 LLM，上下文必须是 “当前 section + 精准证据片段”。
- **可扩展**：搜索工具可替换（Google/Bing/Jina/SerpAPI/智谱 web_search），存储可替换（JSONL 本地 / SQLite / 向量库）。

### 1.3 系统模块
建议在仓库新增（或按你现有风格组织）这些模块：
- [agents/](cci:7://file:///Users/gongfan/WebWeaver1/%E5%8F%82%E8%80%83%E9%A1%B9%E7%9B%AE/agents:0:0-0:0)
  - [base_agent.py](cci:7://file:///Users/gongfan/WebWeaver1/%E5%8F%82%E8%80%83%E9%A1%B9%E7%9B%AE/agents/base_agent.py:0:0-0:0)：统一 Agent 接口（参考项目 BaseAgent 思路）
  - `planner_agent.py`
  - `writer_agent.py`
- `tools/`
  - `web_search.py`：搜索引擎适配器
  - `url_filter.py`：基于 title/snippet 的 URL 过滤（LLM）
  - `page_fetcher.py`：抓取页面 HTML/PDF
  - `page_parser.py`：抽正文、去噪、分段
  - `summarizer.py`：query-relevant summary
  - `evidence_extractor.py`：抽取可验证证据（引文/数据点/定义/事实）
- [memory/](cci:7://file:///Users/gongfan/WebWeaver1/%E5%8F%82%E8%80%83%E9%A1%B9%E7%9B%AE/agents/graph/memory:0:0-0:0)
  - `evidence_bank.py`：Memory Bank（核心）
  - [schemas.py](cci:7://file:///Users/gongfan/WebWeaver1/%E5%8F%82%E8%80%83%E9%A1%B9%E7%9B%AE/apis/schemas.py:0:0-0:0)：Evidence / Source / OutlineNode 等数据结构
  - `persistence.py`：落盘（jsonl/sqlite）
- `orchestrator/`
  - `runner.py`：串联 Planner -> Writer
  - `state.py`：全局状态机（outline + evidence stats + step count）
- `evaluation/`
  - `outline_judge.py`：使用 [docs/PromptOutlineJudgement.md](cci:7://file:///Users/gongfan/WebWeaver1/docs/PromptOutlineJudgement.md:0:0-0:0) + criteria 进行自动评测（可选，但建议做）
- [prompts/](cci:7://file:///Users/gongfan/WebWeaver1/%E5%8F%82%E8%80%83%E9%A1%B9%E7%9B%AE/prompts:0:0-0:0)
  - `planner_system.txt`, `planner_user.txt`
  - `writer_system.txt`, `writer_user.txt`
  - `url_filter_system.txt` 等

---

## 2. 数据结构设计（必须落地）

### 2.1 Evidence Bank（证据记忆库）
#### 2.1.1 Evidence 记录结构（建议 Pydantic）
- `evidence_id`: `id_1` / `id_2` …（全局唯一、可复用）
- `query`: 触发该证据的搜索 query
- `source`:
  - `url`
  - `title`
  - `publisher` / `author`（能抽则抽）
  - `published_at`（能抽则抽）
  - `retrieved_at`
- `summary`: 与 query 相关的摘要（用于 Planner 迭代）
- `evidence_items`: List[EvidenceItem]
  - `type`: `quote|data|definition|claim|case`
  - `content`: 证据内容（尽量是可验证的原文引述或数据）
  - `location`: 页面位置（段落编号/页面页码/章节标题）
  - `confidence`: 0-1（LLM 自评，后续可删）
- `raw_text_ref`: 原文存储引用（文件路径/对象存储 key），避免把 raw_text塞进主结构
- `hash`: URL+内容 hash（去重）
- `tags`: 可选（主题、维度、实体）

#### 2.1.2 Evidence Bank API（必须实现）
- `add_source(evidence: Evidence) -> evidence_id`
- `get(evidence_id) -> Evidence`
- `bulk_get(ids: list[str]) -> list[Evidence]`
- `search(query, top_k) -> list[Evidence]`（可选：向量检索；第一阶段可以先不做）
- `stats()`：证据数、来源分布、token 估计

### 2.2 Outline 数据结构
Planner 输出的大纲必须能“机器解析”，不能只是纯 Markdown。
推荐两种方案（二选一）：

#### 方案 A：XML 标签（与案例研究一致）
- Planner 每次 `write_outline` 输出：
```text
<write_outline>
# Title ...
## 1 ...
### 1.1 ... <citation>id_1,id_2</citation>
...
</write_outline>
```
优点：与 docs 案例一致，易抽取 citation。

#### 方案 B：JSON AST（更稳健）
- `OutlineNode`:
  - `id`: `sec_1_2`
  - `title`
  - `level`: 1/2/3
  - `bullets`: list[str]（该节要点、论证路径、方法、图表建议等）
  - `citations`: list[evidence_id]
  - `children`: list[OutlineNode]

**建议：内部用 JSON AST**，对外展示可渲染为 Markdown/XML。这样 Writer 迭代写 section 更稳。

---

## 3. Planner 设计（动态研究循环）

### 3.1 Planner 输入输出
- **输入**：
  - `user_query`
  - 当前 `outline`（可能为空）
  - `evidence_bank` 的 summaries（注意：只给 summary，不给全量 raw）
  - 当前进度状态：轮次、已搜过的 query、已覆盖维度等
- **输出**（严格三选一）：
  - `Action.Search(queries: list[str], goal: str)`
  - `Action.WriteOutline(outline_ast or outline_text)`
  - `Action.Terminate(reason: str)`

### 3.2 Planner 循环停止条件（Terminate 判定）
至少满足：
- 大纲覆盖用户指令要求（格式/章节/范围）
- 每个关键章节都有足够 citation（**Support** 维度最低要求： somewhere 有 URL；更推荐每节都有）
- evidence 数量与广度达标（可配置阈值，如 `>= N_sources` 且覆盖 `>= M_dimensions`）

### 3.3 Search 子流程（Evidence acquisition）
对每个 Planner 产出的 query：
1. `web_search(query, k)` 获取候选（title/snippet/url）
2. `url_filter_llm`：仅基于 title/snippet 选出相关 URL（减少噪声）
3. 对每个 URL：
   - `fetch_page(url)`：获取 HTML/PDF
   - `parse_content()`：抽正文、分段、清洗
   - `summarize(query, content)`：生成 query-relevant summary（返回给 Planner）
   - `extract_evidence(query, content)`：抽取可验证证据点（写入 evidence_bank）
4. 去重：URL 去重 + 内容 hash 去重

### 3.4 Outline 优化子流程（Outline optimization）
当 Planner 选择 `write_outline`：
- 输入：`user_query + 当前 outline + 最近新增 evidence summaries`
- 输出：更新后的 outline（必须带 citations）
- 约束：
  - 章节层级清晰（H1/H2/H3 或编号体系一致）
  - 每个事实/计划论点尽量标注 citations
  - 必须包含：`References` 或等价“来源列表”章节（否则 Support=0 风险极高）
  - Balance/Breadth：在不确定/争议主题中必须有 `limitations / counterarguments / risks` 等 section

### 3.5 Planner Prompt 关键点（必须写进 prompts）
- 强制输出 action 格式（参考 `docs/案例研究.md`）：
  - `<think>...</think>`
  - `<tool_call>{"name":"search", "arguments": {...}}</tool_call>`
  - `<tool_response>...</tool_response>`
  - `<write_outline>...</write_outline>`
  - `<terminate>...</terminate>`
- 明确：`write_outline` 必须包含 `<citation>` 标签且引用已有的 `id_x`。

---

## 4. Writer 设计（基于大纲的分段写作）

### 4.1 Writer 输入输出
- 输入：
  - `outline_ast`
  - `evidence_bank`
  - 写作配置：受众、语气、长度、格式（若用户指定）
- 输出：
  - `report_markdown`（最终报告）
  - 可选：`section_outputs`（便于调试）

### 4.2 Writer 写作策略（严格按 section）
对每个 section node（建议按 H2）：
1. 收集该 node 的 citations（包含子节点 citations 也可）
2. `evidence_bank.bulk_get(citation_ids)`
3. 组装 **本节专用上下文**：
   - 本节标题 + 要点 bullets
   - 本节 evidence items（引用+URL+关键句/数据）
4. 生成本节内容：
   - 每段尽量引用（例如脚注形式 `(Source: ... URL)` 或 `[^id_1]`）
   - 遇到证据不足：必须显式标注 “尚无充分来源支撑/需要进一步验证”
5. 输出 `<write>...</write>` 轨迹（与案例一致）
6. 继续下一节，直到 `<terminate>`

### 4.3 引用渲染规范（建议统一）
内部引用用 evidence_id，最终渲染：
- 文中脚注：`[^id_12]`
- 末尾 References：
  - `[^id_12]: Title - Publisher (Date). URL`

最低要求：最终输出**必须出现 URL 列表或内联 URL**，否则 Support 评分必为 0。

---

## 5. 工具与适配层设计

### 5.1 Web Search 工具
接口：
- `search(query: str, max_results: int) -> list[SearchResult]`
`SearchResult`:
- `title`
- `snippet`
- `url`
- `source`（引擎名）
- `rank`

实现策略：
- 第一阶段可用任意可访问方案（例如 SerpAPI / Bing / DuckDuckGo / 自建抓取）
- 若复用 `参考项目` 里智谱 `search_web_zhipu`，注意：
  - **不要硬编码 key**（参考项目里出现硬编码 key，这是安全风险；本项目必须改成 env）
  - 搜索结果要标准化成统一 `SearchResult`

### 5.2 页面抓取与解析
- HTML：Readability/boilerplate removal
- PDF：pdfminer/pymupdf
- 统一输出：`ParsedDocument {url, title, text, headings?, paragraphs[]}`

### 5.3 LLM Client 抽象
参考 `参考项目` 的 “LLM 客户端管理+prompt 解耦” 思路：
- `LLMClient.chat(messages)->str`
- `LLMClient.stream(messages)->iterator[str]`（可选）
- 所有模型/BASE_URL/API_KEY 走环境变量或配置文件

---

## 6. 状态机与编排（Orchestrator）

### 6.1 全流程时序（对齐 `docs/工作流程.md`）
1. 用户输入 `Query`
2. Planner Round 1：
   - Think -> Search -> Observations（summary/evidence 入库）-> WriteOutline
3. Planner Round N：
   - Search / WriteOutline 交错迭代
4. Planner Terminate：输出最终 outline
5. Writer：
   - 对 outline 分章节 Retrieve(citations)->Write(section)
6. Writer Terminate：输出最终 Report

### 6.2 Orchestrator 伪代码（落地级）
```python
state = {
  "query": user_query,
  "outline": None,
  "evidence_bank": EvidenceBank(...),
  "planner_round": 0,
}

while True:
  action = planner.step(state)
  if action.type == "search":
     results = web_search(action.queries)
     urls = url_filter(results)
     for url in urls:
        doc = fetch_parse(url)
        summary = summarize(user_query, doc.text)
        evidence = extract_evidence(user_query, doc.text, url_meta)
        evidence_bank.add(evidence)
     state["planner_round"] += 1
  elif action.type == "write_outline":
     state["outline"] = action.outline
  elif action.type == "terminate":
     break

report = writer.write(state["outline"], state["evidence_bank"])
return report
```

### 6.3 防崩策略（必须）
- 最大迭代次数 `max_planner_steps`
- 单次搜索最大 URL 数 `max_urls_per_query`
- 单 URL 最大解析 token 数（超长截断+保留关键段落）
- 出错降级：某 URL 失败不影响整体；写入日志并继续

---

## 7. 自动评测（可选但建议做）

### 7.1 Outline Judge
对 Planner 输出的大纲，用 [docs/PromptOutlineJudgement.md](cci:7://file:///Users/gongfan/WebWeaver1/docs/PromptOutlineJudgement.md:0:0-0:0) + [docs/judgementcriteria.md](cci:7://file:///Users/gongfan/WebWeaver1/docs/judgementcriteria.md:0:0-0:0) 做自动打分：
- 对每个 criterion 单独调用一次 LLM Judge，得到 JSON：`{"rating":x,"justification":"..."}`  
- 汇总评分并输出诊断，用于调参：
  - 若 Support=0：说明输出里没有 URL/citation -> 必须修 prompt 或渲染逻辑

---

## 8. 目录与里程碑（你按这个顺序写代码最稳）

### Milestone A：最小闭环（可跑通）
- **A1**：实现 `EvidenceBank`（本地内存+jsonl 持久化）
- **A2**：实现 `web_search`（先用最简单方案）
- **A3**：实现 `fetch+parse`（HTML 基础抽取）
- **A4**：实现 `summarize` 与 `extract_evidence`（LLM 调用）
- **A5**：实现 `PlannerAgent`：支持 `search/write_outline/terminate`，且输出轨迹标签
- **A6**：实现 `WriterAgent`：按 outline citations 分段写作，输出引用与 References
- **A7**：实现 `runner`：串起来跑一个 query，得到最终 markdown 报告

### Milestone B：质量增强
- **B1**：URL 过滤两阶段（title/snippet -> LLM 过滤 -> 再抓取）
- **B2**：证据去重与可信度标注
- **B3**：outline AST 化与稳定解析
- **B4**：自动评测 Outline（judge）

### Milestone C：工程化
- **C1**：CLI：`python -m webweaver "your query"`
- **C2**：API（可选 SSE）
- **C3**：配置解耦（env/config）
- **C4**：日志与可观测（每步产物落盘：search results、parsed docs、outline versions）

---

## 9. 你需要我确认的实现选择（开始写代码前必须定）
为了后续实现不走弯路，你需要明确：
1. **运行形态**：先做 CLI 还是 FastAPI（SSE）？
2. **搜索引擎**：你希望用哪个？（是否允许复用 `参考项目` 智谱搜索；如允许，必须改为 env key）
3. **大纲格式**：内部用 `Outline AST(JSON)` 还是纯文本+XML citations？
4. **证据存储**：先本地 jsonl 还是 SQLite？

你回复这 4 个点后，我就能把计划转成具体文件结构与逐文件实现清单。

---

# 重要说明（Ask mode 限制）
- 由于你当前是 **Ask mode**，我只能把内容发给你复制粘贴。
- 你把上面内容粘贴进 [plan.md](cci:7://file:///Users/gongfan/WebWeaver1/plan.md:0:0-0:0) 后，**切换到 Code mode**，我才能开始：
  - 创建目录/文件
  - 写代码
  - 修复依赖与可运行入口

---

## 当前状态总结
- **已完成**：基于 [docs/](cci:7://file:///Users/gongfan/WebWeaver1/docs:0:0-0:0) 与 `参考项目` 的业务逻辑提炼与架构抽象；输出了可落地的超详细设计文档内容。
- **待你执行**：
  - 把上述内容复制到 [plan.md](cci:7://file:///Users/gongfan/WebWeaver1/plan.md:0:0-0:0)
  - 回答第 9 节的 4 个选择
  - 切换到 **Code mode**，我即可开始按计划写代码并跑通闭环