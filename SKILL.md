---
name: activity-plan-builder
description: 生成中国高校大型活动方案的交互式工作流。先用本地 Studio 让用户勾选章节模块、一键导入学校字体格式、挑选预设表格样式，再补全内容并导出符合公文版式的 DOCX。当用户要写活动方案、活动策划书、晚会/音乐节/升旗/迎新/运动会方案，或要求套用学校 Word 格式时使用。
license: MIT
---

# 活动方案工坊（Activity Plan Builder）

面向大学大型活动（晚会、音乐会、音乐节、升旗仪式、迎新、运动会、社团活动等）的 DOCX 方案生成器。核心是**先让用户在浏览器里做选择，再由 Agent 补全内容**，避免一次性生成一大段无法控制的文字。

## 适用场景

- 用户要写「XX 活动方案 / 策划书 / 活动策划」
- 用户有学校的 Word 格式要求（DOCX 模板或一段文字规范）
- 用户想在多个章节模块、表格样式之间做选择
- 需要规范的 A4 公文版式：标题小标宋、一级标题黑体、正文仿宋、固定行距、页码

## 环境要求

- Python 3.10+
- `python-docx`（见 `requirements.txt`）

```bash
python -m pip install -r requirements.txt
```

## 推荐工作流（必须按顺序）

### 1. 创建方案

```bash
python scripts/apb.py new --dir "<work_dir>" --title "联合研究生院元旦晚会" --type "晚会" \
  --date 2026-12-28 --time "19:00—21:30" --location "文化路校区大礼堂" \
  --organizer "联合研究生院" --undertaker "联合研究生院学生会" \
  --brief "面向全院研究生的元旦联欢活动，含节目展演、互动抽奖与新年寄语。"
```

可选参数：`--theme`、`--audience`、`--modules`、`--style`、`--table-style`。

### 2. 打开交互式 Studio（关键步骤）

```bash
python scripts/apb.py studio --dir "<work_dir>" --open --wait
```

- 浏览器会打开五步配置台：基本信息 → 模块编排 → 版式规范 → 表格样式 → 内容与导出
- 用户在页面上勾选模块、导入学校 DOCX 或粘贴文字格式、挑选表格样式
- 用户点击「交给 Agent」后，命令打印 `READY <plan.json>` 并退出
- 如果用户直接点了「生成 DOCX」，命令同样会返回，方案状态为 `built`

> `--wait` 默认最多等 30 分钟。Agent 应把这条命令放在前台执行并等待结果，不要并行做别的写入操作。

### 3. 读取用户选择

```bash
python scripts/apb.py info "<work_dir>/plan.json"
```

然后直接读取 `plan.json`。重点看：

- `modules[].enabled` / `modules[].order`：用户勾选和排序后的章节
- `modules[].needsAgent`：`true` 表示允许你补全，`false` 表示用户已自己写好、不要改写
- `modules[].blocks`：段落 `paragraph`、小标题 `subheading`、列表 `list`、注释 `note`、分页 `pagebreak`
- `modules[].table` / `modules[].attachments`：表格与附件
- `style` / `styleRef`：学校版式（可能来自导入）
- `tableStyles.global` / `tableStyles.byKind`：表格样式

### 4. 补全内容

只补 `needsAgent: true` 且仍有 `【...】` 占位符的内容。写作规则：

- 不编造人名、电话、学号、审批编号、具体金额；未知信息统一写 `【待定】`
- 预算表只补单价/数量的合理占位，合计由引擎自动计算，不要手写合计
- 一级标题顺序由 `order` 决定，不要改标题编号（引擎自动加「一、二、三、」）
- 段落直接写正文，不要带「一、」前缀；小标题用 `subheading`，内容用 `paragraph`
- 每个模块 2—5 段，每段 80—180 字；避免空话堆砌
- 保留用户已经写好的文字与表格结构，只做增量补全

修改后保存 `plan.json`，再校验：

```bash
python scripts/apb.py validate "<work_dir>/plan.json"
```

### 5. 生成 DOCX

```bash
python scripts/apb.py build "<work_dir>/plan.json" -o "<work_dir>/元旦晚会活动方案.docx"
```

返回 `BUILT <path>`。把绝对路径告诉用户，并说明可直接打开修改。

## 学校格式导入

### 从学校 DOCX 模板提取

```bash
python scripts/apb.py import-style "学校模板.docx" -o school-profile.json
python scripts/apb.py build plan.json --style-json school-profile.json
```

自动识别：页边距、标题/一级/二级标题/正文字体字号、行距、首行缩进、对齐、表头底纹与边框。结果含 `source.confidence`（high/medium/low）与 `tableStyleGuess`。

### 从文字要求解析

```bash
python scripts/apb.py parse-style --text "正文仿宋_GB2312三号，行距28磅，首行缩进2字符；标题方正小标宋二号；页边距上3.7厘米、下3.5厘米、左2.8厘米、右2.6厘米。" -o school-profile.json
```

### 在 Studio 中导入

用户可在第 3 步直接拖入 DOCX 或粘贴文字，识别结果会立即应用到 A4 预览；也可保存为「我的学校」存到浏览器 localStorage。

## 表格样式

Studio 第 4 步只展示**结构不同**的 5 套样式（默认 `three-line`），并可一键关闭表格（`tableStyles.enabled = false` 时导出不含任何表格）：

| id | 名称 | 适用 |
| --- | --- | --- |
| three-line | 学术三线表 | 简约、汇报（默认） |
| horizontal-only | 仅横线 | 流程与日程 |
| budget | 预算专用 | 经费预算 |
| form | 表单样式 | 报名表、回执 |
| timeline | 时间轴 | 筹备推进 |

另有 gov-grid / dark-header / zebra-gray / zebra-blue 仅保留数据兼容，不出现在 Studio 中，旧方案引用时仍可导出。

可按表格分类覆盖：`tableStyles.byKind` 支持 `schedule / budget / division / materials / promotion / timeline / risk / awards / form / program`。

## 模块 id

- 核心（不可关闭）：`theme` `time_place` `audience` `content`
- 推荐：`organization` `registration` `budget` `signature`（默认启用）；`schedule` `requirements` `background` `significance` `promotion` `selection` `awards` `division` `materials` `safety` `civilized`（默认关闭，可勾选）
- 进阶：`timeline` `venue` `risk` `sponsorship` `attachment` `contact` `review`

完整目录与默认内容见 `assets/modules.json`；可用 `python scripts/apb.py list modules` 查看。

## 表格数据契约

```json
{
  "kind": "schedule",
  "title": "活动流程",
  "headers": ["时间", "环节", "具体内容", "负责部门"],
  "widthsCm": [3.0, 3.2, 7.0, 3.0],
  "rows": [["18:30—19:00", "观众入场", "检票、引导入座", "会务组"]],
  "total": false,
  "merges": [{"r": 1, "c": 0, "rowspan": 2, "colspan": 1}],
  "numericColumns": [4],
  "totalLabel": "合计"
}
```

- `merges` 的 `r/c` 是数据行/列下标（不含标题行与表头行）
- 预算表设置 `"kind": "budget"`、`"total": true`，引擎按「单价 × 数量」重算小计与合计
- 附件表：`modules[].attachments[] = {title, subtitle, table}`，导出时自动另起一页并加「附件一」

## MCP 接入（Claude Desktop / Cursor / TRAE）

`mcp/server.py` 是零依赖 stdio MCP 服务，提供工具：

`list_modules` `list_table_styles` `create_plan` `open_studio` `wait_for_handoff` `get_plan` `import_school_style` `build_docx` `validate` `update`

配置示例见 `mcp/config-examples/`。典型调用顺序：

1. `create_plan` 建方案
2. `open_studio` 打开配置台
3. `wait_for_handoff` 等用户点「交给 Agent」
4. `get_plan` 读取选择
5. 补全后 `build_docx` 生成文档

## CLI 速查

| 命令 | 作用 |
| --- | --- |
| `apb.py new` | 创建 plan.json |
| `apb.py studio` | 打开交互式配置台 |
| `apb.py build` | 生成 DOCX |
| `apb.py import-style` | 从 DOCX 提取格式 |
| `apb.py parse-style` | 解析文字格式要求 |
| `apb.py validate` | 校验结构与占位符 |
| `apb.py info` | 输出方案摘要 |
| `apb.py list modules/tables/styles` | 列出模块、表格样式、版式预设 |
| `apb.py version` | 查看当前版本 |
| `apb.py update` | 从 zip / URL 更新技能（发布见 README「升级更新」） |

## 目录结构

```
activity-plan-builder/
├── SKILL.md
├── VERSION           # 版本号
├── requirements.txt
├── assets/            # 模块库、表格样式、版式预设、Studio 前端
├── scripts/           # apb.py / apb_core.py / docx_engine.py / style_extract.py / updater.py / studio_server.py
├── mcp/server.py      # MCP stdio 适配层
└── examples/          # 示例方案
```

## 注意事项

- Studio 只监听 `127.0.0.1`，仅本机可访问；上传模板限制 25MB
- 生成前若仍有大量 `【待补充】`，先向用户确认关键信息，不要凭空编造
- 学校格式识别是启发式的：置信度低时提醒用户在 Studio 第 3 步手动微调
- DOCX 中文字体依赖本机已安装的字体；未安装时会回退，但版式参数仍保留
