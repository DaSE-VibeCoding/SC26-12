# 财报分析助手 AI 编程操作手册 v4

本文档用于指导“依靠 AI 助手逐步编写代码”的开发过程。项目当前阶段聚焦 Python 版 MVP，暂不优先开发完整前端。


# 0. 路径总约束：只在一处定义项目根目录

## 0.1 项目根目录

所有代码、脚本、测试和文档中都不得直接写入本机绝对路径。项目只允许在一处定义项目根目录。

建议使用以下任一方式：

```text
PROJECT_ROOT=.
```

或：

```text
PROJECT_ROOT=/path/to/FinancialReportAssistant
```

换电脑、换磁盘或换用户名时，只允许修改这一处配置。业务代码必须通过 `PROJECT_ROOT` 拼接相对路径。

## 0.2 推荐配置文件

建议建立：

```text
configs/paths.yaml
```

内容示例：

```yaml
project_root: "."

lookup_dir: "lookupfiles"
input_example_dir: "input_example"
raw_reports_dir: "data/raw_pdfs"
raw_calls_dir: "data/raw_calls"
processed_dir: "data/processed"
outputs_dir: "data/outputs"
logs_dir: "logs"

company_master_file: "lookupfiles/STK_LISTEDCOINFOANL_20200101_20251231.xlsx"
company_master_desc_file: "lookupfiles/STK_LISTEDCOINFOANL[DES][xlsx].txt"
cninfo_address_file: "lookupfiles/web_address.txt"
```

## 0.3 路径生成原则

所有模块必须通过统一路径模块生成路径：

```text
src/fintrace/shared/paths.py
```

建议接口：

```python
get_project_root()
get_lookup_path(name)
get_input_example_path(name)
get_raw_report_path(company_code, filename)
get_raw_call_path(company_code, filename)
get_processed_dir(feature, company_code, run_id, step_name=None)
get_output_dir(feature, company_code, run_id)
```

禁止写法：

```python
pdf_path = r"<本机绝对路径>\input_example\贵州茅台：贵州茅台2026年第一季度报告.pdf"
```

正确写法：

```python
pdf_path = paths.get_input_example_path("贵州茅台：贵州茅台2026年第一季度报告.pdf")
```

## 0.4 当前资料的相对路径映射

当前用户提供的本机文件，在项目内统一映射为以下相对路径：

| 资料 | 相对路径 | 用途 |
|---|---|---|
| 公司基础信息 Excel | `lookupfiles/STK_LISTEDCOINFOANL_20200101_20251231.xlsx` | 股票代码解析、公司基础信息、行业、上市状态 |
| 公司基础信息字段说明 | `lookupfiles/STK_LISTEDCOINFOANL[DES][xlsx].txt` | 字段含义说明 |
| 巨潮资讯网入口 | `lookupfiles/web_address.txt` | 查询公告与报告发布时间 |
| 贵州茅台样例报告 | `input_example/贵州茅台：贵州茅台2026年第一季度报告.pdf` | 财报 PDF 抽取与证据链样例 |

文档中可以说明原始来源，但代码只能使用相对路径。

---

# 1. 项目目标

构建一个以公司为中心、分析结果可追溯、可人工复核的上市公司信息分析工具。

用户只需要输入一个公司的股票代码，例如：

```text
600519
```

系统根据股票代码识别：

- 公司名称；
- 所属交易所；
- 行业分类；
- 上市状态；
- 可获得的财报、披露日历或电话会资料。

股票代码是系统内部识别公司的唯一主键。公司简称仅用于展示，不作为数据关联主键。

产品需要解决三个问题：

1. 公司什么时候披露财报；
2. 公司披露了什么，财务指标发生了什么变化，分析结果是否可以复核；
3. 管理层如何解释公司的经营变化。

---

# 2. 三项核心功能

## 2.1 功能一：日历通知看板

用户输入公司股票代码后，可以查看该公司近几年的：

- 财报报告期；
- 报告类型；
- 预约披露日期；
- 预约披露日期变更记录；
- 实际披露日期；
- 实际发布时间；
- 数据来源与人工复核入口。

该功能主要回答：

```text
这家公司将在什么时候披露财报，过去实际在什么时候披露财报？
```

## 2.2 功能二：财务分析看板与数据验证

财务分析页面规划为两部分：

- 左侧：数据可视化页面，展示核心财务指标、近五年纵向变化和行业横向比较。
- 右侧：PDF 阅读器式证据查看器，展示原始财报 PDF，并在 PDF 页面上高亮数据来源。

系统必须保留以下验证链路：

```text
分析结论
  ↓
计算过程
  ↓
标准化数据与单位换算
  ↓
财报 PDF 原始证据
```

右侧证据查看器不是普通文本面板，也不是只展示页码和截图。它应具备类似 WPS PDF 阅读器的核心体验：

- 显示原始 PDF 页面；
- 支持页码跳转、滚动、缩放；
- 根据 `evidence_id` 自动定位到对应页；
- 在 PDF 页面上以半透明高亮框标出数据所在区域；
- 高亮区域应对应 PDF 坐标，而不是仅展示截图裁剪；
- 支持同一指标关联多个来源时同时或分步高亮；
- 保留公式、原始值、单位换算和来源页之间的联动。

## 2.3 功能三：电话会数据处理

电话会功能处理用户提供的录屏、视频或音频文件，自动生成：

- 带时间戳的逐字稿；
- 清理后的可读稿；
- 管理层经营亮点；
- 业绩指引；
- 管理层解释；
- 投资者重点问题与回答；
- 每条结果对应的原始音视频时间位置。

该功能不负责将电话会内容与财报数据进行交叉验证。

---

# 3. 可验证交付规则

本项目每次让 AI 写代码，都必须遵守 Vibe Coding 可验证交付流程。

## 3.1 写代码前必须回答五个问题

在修改任何代码前，AI 必须先回答：

1. 本次目标是什么；
2. 本次非目标是什么；
3. 事实来源是什么；
4. 允许和禁止修改的范围是什么；
5. 用什么证据证明完成。

如果任一问题无法回答，先读取相关文件或询问用户，不得直接猜测。

## 3.2 任务契约模板

每个实现任务必须先形成任务契约：

```yaml
task:
  goal: 本次必须实现的结果
  non_goals:
    - 本次明确不处理的事项
  source_of_truth:
    - 用户当前明确要求
    - 本手册 v3
    - 相关代码、测试、样例数据
  scope:
    allowed:
      - 本功能相关模块
      - 本功能相关测试
      - 本功能相关文档
    forbidden:
      - 无关功能重构
      - 删除用户数据
      - 修改公共接口但不更新调用方
      - 在代码中硬编码绝对路径
  constraints:
    - company_code 是公司唯一主键
    - 三项功能独立闭环
    - 中间结果必须落盘
    - 错误必须定位到具体步骤
  acceptance_criteria:
    - 一条命令可运行
    - 输出文件实际生成
    - 质量报告实际生成
    - 测试通过或明确说明失败原因
  evidence_required:
    - 实际执行命令
    - 测试结果
    - 输出目录
    - 关键日志
    - 已知限制
  rollback:
    - 保留修改前文件
    - 可通过版本控制回退
```

## 3.3 停止条件

遇到以下情况必须停止并请求确认：

- 需要删除或迁移用户数据；
- 需要修改公共 API；
- 需要安装或更换核心依赖；
- 需要绕过登录、验证码或权限；
- 文档、代码和测试互相矛盾且无法判断；
- 只能通过跳过测试、硬编码结果、吞掉异常或扩大超时来“解决”问题；
- 真实外部网站不可访问且没有本地样例数据可替代。

## 3.4 交付报告模板

每次功能完成后，AI 必须输出：

```markdown
## 任务结论
PASS / ESCALATE / REJECT

## 修改摘要

## 修改文件

## 关键设计决定

## 验证命令和结果

## 输出文件

## 未验证事项

## 风险和限制

## 回滚方式

## 后续事项
```

---

# 4. 统一公司输入与公司主数据

## 4.1 公司唯一标识

系统统一使用：

```text
company_code
```

示例：

```text
600519
```

兼容输入：

```text
600519
600519.SH
```

进入系统后标准化为：

```json
{
  "company_code": "600519",
  "exchange": "SSE"
}
```

## 4.2 公司基础信息数据源

公司基础信息来自：

```text
lookupfiles/STK_LISTEDCOINFOANL_20200101_20251231.xlsx
```

字段说明来自：

```text
lookupfiles/STK_LISTEDCOINFOANL[DES][xlsx].txt
```

核心字段包括：

| 字段 | 含义 | 用途 |
|---|---|---|
| `Symbol` | 股票代码 | 公司唯一主键 |
| `ShortName` | 股票简称 | 展示 |
| `EndDate` | 统计截止日期 | 年度版本选择 |
| `FullName` | 中文全称 | 公司展示与报告 |
| `IndustryName` | 行业名称 | 同行筛选与展示 |
| `IndustryCode` | 行业代码 | 同行筛选 |
| `IndustryNameD` | 中国上市公司协会行业名称 | 2023 年后优先参考 |
| `IndustryCodeD` | 中国上市公司协会行业代码 | 2023 年后优先参考 |
| `LISTINGDATE` | 首次上市日期 | 公司基础信息 |
| `LISTINGSTATE` | 上市状态 | 是否正常上市 |
| `RegisterAddress` | 注册地址 | 公司基础信息 |
| `OfficeAddress` | 办公地址 | 公司基础信息 |
| `Secretary` | 董事会秘书 | 公司基础信息 |
| `SecretaryTel` | 董秘电话 | 公司基础信息 |
| `SecretaryEmail` | 董秘邮箱 | 公司基础信息 |
| `Website` | 公司网址 | 公司基础信息 |
| `MAINBUSSINESS` | 主营业务 | 公司概览 |

## 4.3 年度版本选择规则

公司基础信息按 `Symbol + EndDate` 查询。

规则：

1. 默认使用目标年份同年 `EndDate` 最接近年末的记录。
2. 如果查询 2026 年，但 Excel 当前没有 2026 年数据，则完全参考 2025 年数据。
3. 发生年度回退时，必须在输出中标记：

```json
{
  "company_info_year_requested": 2026,
  "company_info_year_used": 2025,
  "company_info_fallback": true,
  "fallback_reason": "2026 company master data is not available; use 2025 record."
}
```

4. 不得用模型猜测 2026 年公司基础信息变化。
5. 不得用公司简称模糊匹配替代股票代码匹配。

## 4.4 贵州茅台样例公司对象

对 `600519`，2026 年查询公司基础信息时使用 2025 年记录。

样例输出：

```json
{
  "company_code": "600519",
  "company_name": "贵州茅台",
  "company_full_name": "贵州茅台酒股份有限公司",
  "exchange": "SSE",
  "industry_code": "C15",
  "industry_name": "酒、饮料和精制茶制造业",
  "listing_date": "2001-08-27",
  "listing_status": "正常上市",
  "registered_address": "贵州省仁怀市茅台镇",
  "office_address": "贵州省仁怀市茅台镇",
  "secretary": "余思明(代)",
  "secretary_tel": "0851-22386002",
  "secretary_email": "mtdm@moutaichina.com",
  "website": "www.moutaichina.com",
  "main_business": "茅台酒及系列酒的生产与销售。",
  "company_info_year_requested": 2026,
  "company_info_year_used": 2025,
  "company_info_fallback": true
}
```

---

# 5. 巨潮资讯网与报告发布时间

## 5.1 数据源

巨潮资讯网入口保存在：

```text
lookupfiles/web_address.txt
```

当前内容：

```text
巨潮资讯网https://www.cninfo.com.cn/new/index.jsp
```

## 5.2 使用方式

公司发布年报或定期报告的时间，需要将人类输入的股票代码放到巨潮资讯网中搜索。

MVP 推荐流程：

1. 读取 `lookupfiles/web_address.txt` 获取巨潮资讯网入口。
2. 使用用户输入的 `company_code` 搜索公告。
3. 按公司代码、公司名称、报告标题、报告期和报告类型筛选公告。
4. 记录公告标题、公告发布日期、公告发布时间、公告链接、来源网站和抓取时间。
5. 保存原始检索结果，便于人工复核。

## 5.3 年报发布时间字段

建议输出字段：

```text
company_code
company_name
report_period
report_type
announcement_title
announcement_date
announcement_time
source_site
source_url
query_keyword
queried_at
manual_review_required
```

## 5.4 人工输入与自动化边界

巨潮资讯网可能存在验证码、反爬、网络不可用或页面结构变化。

若自动化检索失败，系统应：

- 保存失败日志；
- 输出人工检索指引；
- 不得虚构发布时间；
- 不得用模型常识补全公告时间；
- 允许用户手工填入公告链接和公告时间，再进入后续流程。

---

# 6. 电话会输入规则

## 6.1 用户必须提供媒体文件

电话会功能不自动搜索电话会录音。人类必须提供电话会录屏、视频或音频文件。

必填输入：

```text
company_code
media_path
```

建议把用户提供的媒体文件放入：

```text
data/raw_calls/{company_code}/
```

示例：

```text
data/raw_calls/600519/600519_2026Q1_call.mp4
data/raw_calls/600519/600519_2026Q1_call.mp3
```

## 6.2 媒体登记

系统必须先登记媒体文件，再转写。

建议字段：

```text
call_id
company_code
event_date
event_type
media_path
media_hash
duration_seconds
file_size
source_type
processing_status
```

## 6.3 电话会功能边界

电话会模块只处理：

- 媒体文件校验；
- 音频提取与预处理；
- ASR 转写；
- 说话人分离；
- 主题分段；
- 经营亮点、业绩指引、投资者问答提取；
- 时间戳定位。

电话会模块不得：

- 自动搜索或下载电话会录音；
- 虚构说话人身份；
- 将模糊展望改写为确定承诺；
- 与财报数据做交叉验证；
- 依赖日历模块或财务分析模块输出。

---

# 7. 推荐目录结构

```text
FinancialReportAssistant/
  FinancialReportAssistant_MANUAL_v3.md
  README.md
  requirements.txt

  configs/
    paths.yaml
    indicators.yaml
    calendar_rules.yaml
    peer_rules.yaml
    call_extraction_rules.yaml

  lookupfiles/
    STK_LISTEDCOINFOANL_20200101_20251231.xlsx
    STK_LISTEDCOINFOANL[DES][xlsx].txt
    web_address.txt

  input_example/
    贵州茅台：贵州茅台2026年第一季度报告.pdf

  data/
    raw_calendar/
    raw_pdfs/
    raw_calls/

    processed/
      calendar/
      financial/
      calls/

    outputs/
      calendar/
      financial/
      calls/

  logs/

  src/
    fintrace/
      __init__.py

      shared/
        company_resolver.py
        config.py
        paths.py
        models.py
        logging_utils.py
        exceptions.py

      calendar/
        cninfo_source.py
        normalization.py
        timeline.py
        exporter.py
        pipeline.py

      financial/
        report_registry.py
        pdf_ingestion.py
        table_extraction.py
        normalization.py
        evidence.py
        pdf_viewer.py
        highlight_exporter.py
        analysis.py
        peer_comparison.py
        exporter.py
        pipeline.py

      calls/
        media_registry.py
        audio_preprocessing.py
        transcription.py
        speaker_processing.py
        content_extraction.py
        exporter.py
        pipeline.py

  scripts/
    run_calendar.py
    run_financial.py
    run_call.py
    run_feature.py

  tests/
    fixtures/
      calendar/
      financial/
      calls/

    test_paths.py
    test_company_resolver.py
    test_calendar_pipeline.py
    test_financial_pipeline.py
    test_evidence.py
    test_call_pipeline.py
```

---

# 8. 三项功能独立实现原则

三项功能可以共享公司解析、路径管理、日志、错误类型和运行状态，但业务处理流程必须独立。

禁止依赖：

```text
日历功能 → 财务分析功能
日历功能 → 电话会功能
财务分析功能 → 日历功能
财务分析功能 → 电话会功能
电话会功能 → 日历功能
电话会功能 → 财务分析功能
```

允许共享：

```text
日历功能 → shared/company_resolver.py
财务分析功能 → shared/company_resolver.py
电话会功能 → shared/company_resolver.py

日历功能 → shared/paths.py
财务分析功能 → shared/paths.py
电话会功能 → shared/paths.py
```

每项功能必须独立具备：

- 输入校验；
- step-by-step 处理流程；
- 中间结果保存；
- 最终输出；
- 质量报告；
- 运行日志；
- 单元测试；
- 最小 demo；
- 独立运行脚本。

---

# 9. 共享模块一：路径管理

## 9.1 功能目标

统一管理项目内所有文件路径，保证代码可迁移。

## 9.2 输入

```text
configs/paths.yaml
```

## 9.3 处理步骤

1. 读取 `PROJECT_ROOT`。
2. 解析 `configs/paths.yaml`。
3. 将所有配置路径解析为项目根目录下的绝对路径对象。
4. 校验关键输入文件是否存在。
5. 输出所有业务模块可复用的路径接口。

## 9.4 验收标准

- 代码中搜索不到本机绝对路径前缀；
- 更换项目目录后，只需修改 `PROJECT_ROOT` 或不修改任何业务代码；
- 缺少关键文件时错误信息指出具体配置项；
- 测试覆盖 Windows 路径分隔符和中文文件名。

---

# 10. 共享模块二：公司代码解析

## 10.1 功能目标

接收用户输入的股票代码，返回标准化公司对象。

## 10.2 输入

```text
company_code
target_year
```

示例：

```json
{
  "company_code": "600519",
  "target_year": 2026
}
```

## 10.3 Step-by-step

1. 清理输入，删除空格。
2. 识别 `.SH`、`.SZ`、`.BJ` 后缀。
3. 保留六位股票代码字符串。
4. 读取公司主数据 Excel。
5. 按 `Symbol` 精确匹配。
6. 按 `target_year` 查找对应 `EndDate`。
7. 如果 `target_year=2026` 但不存在 2026 记录，回退到 2025。
8. 生成标准公司对象。
9. 记录是否发生年度回退。
10. 保存运行上下文。

## 10.4 输出

```json
{
  "company_code": "600519",
  "company_name": "贵州茅台",
  "company_full_name": "贵州茅台酒股份有限公司",
  "industry_code": "C15",
  "industry_name": "酒、饮料和精制茶制造业",
  "listing_status": "正常上市",
  "company_info_year_requested": 2026,
  "company_info_year_used": 2025,
  "company_info_fallback": true
}
```

## 10.5 验收标准

- 合法代码返回唯一公司；
- 不存在代码返回明确错误；
- 带后缀代码可正确解析；
- 前导零不丢失；
- 2026 查询回退 2025 时有明确标记；
- 三项功能返回相同公司对象。

---

# 11. 功能一：日历通知看板

## 11.1 功能目标

用户输入公司股票代码后，从巨潮资讯网或本地人工录入结果获取财报预约披露和实际披露情况。

## 11.2 输入

必填：

```text
company_code
```

可选：

```text
start_year
end_year
report_types
cninfo_manual_file
```

## 11.3 Step-by-step

1. 调用公司解析模块。
2. 读取巨潮资讯网入口。
3. 使用 `company_code` 检索公告。
4. 筛选定期报告公告。
5. 标准化报告类型：`q1`、`semiannual`、`q3`、`annual`。
6. 记录预约披露、变更记录和实际披露时间。
7. 保存原始检索结果。
8. 生成日历事件表。
9. 执行质量检查。
10. 输出看板数据和运行日志。

## 11.4 输出

```text
data/outputs/calendar/{company_code}/{run_id}/calendar_events.csv
data/outputs/calendar/{company_code}/{run_id}/schedule_changes.csv
data/outputs/calendar/{company_code}/{run_id}/calendar_timeline.json
data/outputs/calendar/{company_code}/{run_id}/quality_report.json
data/outputs/calendar/{company_code}/{run_id}/run_log.json
```

## 11.5 验收标准

- 输入一个股票代码即可运行；
- 巨潮自动检索失败时不虚构数据；
- 可保存人工复核字段；
- 预约披露、变更和实际披露可以区分；
- 不依赖财务分析和电话会模块。

---

# 12. 功能二：财务分析看板与数据验证

## 12.1 功能目标

用户输入公司股票代码和财报 PDF 后，系统抽取财务数据、生成指标分析，并保留完整证据链。

财务分析功能的验证体验必须体现为“左侧分析结果 + 右侧 PDF 阅读器”。当用户点击任一基础数字、派生指标或分析结论时，右侧应打开原始 PDF、跳转到对应页，并高亮源数据区域。

## 12.2 输入

必填：

```text
company_code
report_pdf_path
```

可选：

```text
report_year
report_period
report_type
indicators
peer_company_codes
```

## 12.3 PDF 输入规则

财报 PDF 应放在项目内相对路径下，例如：

```text
data/raw_pdfs/600519/贵州茅台：贵州茅台2026年第一季度报告.pdf
```

样例文件也可来自：

```text
input_example/贵州茅台：贵州茅台2026年第一季度报告.pdf
```

代码中不得写入该文件的本机绝对路径。

## 12.4 Step-by-step

1. 解析目标公司。
2. 登记 PDF 文件，计算文件哈希。
3. 识别报告期和报告类型。
4. 抽取 PDF 元数据和页面。
5. 抽取表格和文本。
6. 识别财务指标别名。
7. 识别原始单位。
8. 执行单位换算。
9. 生成基础证据 `evidence_id`。
10. 计算派生指标并生成 `trace_id`。
11. 生成纵向分析和同行比较。
12. 生成 PDF 阅读器高亮定位数据。
13. 检查证据链完整性。
14. 输出分析结果、证据索引、PDF 高亮数据和质量报告。

## 12.5 右侧 PDF 阅读器与高亮溯源

右侧数据验证区域必须实现为 PDF 阅读器，而不是普通证据文本面板。

目标交互：

1. 用户在左侧点击一个基础数字，例如“营业收入”。
2. 系统根据该数字的 `evidence_id` 查找 PDF 来源。
3. 右侧 PDF 阅读器打开对应财报 PDF。
4. 阅读器自动跳转到来源页。
5. 页面中对应表格单元格、文本行或数据区域被高亮。
6. 高亮旁或悬浮提示中展示原始值、标准化值、单位、表格名、行列和置信度。
7. 用户可缩放、滚动、翻页，并保持高亮位置与 PDF 页面同步。

阅读器形态参考 WPS PDF 阅读器：

- 左侧或顶部可显示页码、缩放比例、上一页、下一页；
- 主区域展示 PDF 原页；
- 高亮以半透明黄色或蓝色矩形覆盖在 PDF 内容上；
- 当前选中的证据使用更醒目的边框；
- 多个证据来源可以用编号标签区分；
- 用户切换指标时，阅读器自动切换高亮；
- 用户手动滚动时，高亮仍应固定在正确 PDF 坐标位置。

MVP 可以先输出静态 HTML 证据查看器，但必须使用真实 PDF 页面渲染和坐标高亮。不得只输出截图裁剪、纯文本页码或 PDF 下载链接来替代右侧阅读器。

## 12.6 PDF 高亮数据结构

每条 PDF 证据必须包含足够信息，以驱动右侧阅读器跳转和高亮：

```json
{
  "evidence_id": "ev_600519_2026q1_revenue_001",
  "company_code": "600519",
  "report_file": "input_example/贵州茅台：贵州茅台2026年第一季度报告.pdf",
  "report_hash": "...",
  "page_number": 8,
  "page_width": 595.28,
  "page_height": 841.89,
  "coordinate_system": "pdf_points_origin_bottom_left",
  "bbox": {
    "x0": 120.5,
    "y0": 356.2,
    "x1": 218.4,
    "y1": 374.8
  },
  "table_name": "合并利润表",
  "row_label": "营业收入",
  "column_label": "本期发生额",
  "raw_text": "45,789,000,000.00",
  "raw_unit": "元",
  "normalized_value": 45789000000.0,
  "normalized_unit": "元",
  "confidence": 0.92,
  "highlight_style": {
    "fill": "rgba(255, 230, 120, 0.45)",
    "stroke": "#d8a600",
    "stroke_width": 1.5
  }
}
```

坐标要求：

- 必须记录 PDF 原始页坐标；
- 必须记录坐标系，例如 `pdf_points_origin_bottom_left`；
- 如果前端阅读器使用 Canvas 或 DOM 坐标，必须提供转换逻辑；
- 缩放、旋转和不同设备尺寸不得导致高亮错位；
- 如果无法获得精确坐标，必须标记为 `manual_review_required=true`，不得假装精确定位。

## 12.7 派生指标与多来源高亮

派生指标通常由多个基础数字计算而来，例如同比增长率需要本期值和上期值。

点击派生指标时，右侧 PDF 阅读器应支持：

- 高亮本期值来源；
- 高亮上期值来源；
- 若两个来源位于不同 PDF 或不同页，提供来源列表；
- 点击来源列表可切换 PDF、页码和高亮；
- 在公式面板中展示：

```text
同比增长率 = (本期营业收入 - 上期营业收入) / 上期营业收入
```

每个参与计算的输入值都必须有自己的 `evidence_id`。派生指标本身使用 `trace_id` 串联多个 `evidence_id`。

## 12.8 PDF 阅读器输出

MVP 阶段建议输出：

```text
pdf_highlights.json
evidence_viewer.html
viewer_manifest.json
```

其中：

- `pdf_highlights.json` 保存全部证据高亮坐标；
- `viewer_manifest.json` 保存 PDF 文件、页面尺寸、证据索引、默认打开证据；
- `evidence_viewer.html` 提供可人工打开检查的静态 PDF 阅读器页面；
- 后续前端可直接复用这些数据结构实现交互式右侧验证区。

## 12.9 输出

```text
data/outputs/financial/{company_code}/{run_id}/financial_facts.csv
data/outputs/financial/{company_code}/{run_id}/indicator_traces.jsonl
data/outputs/financial/{company_code}/{run_id}/evidence_index.jsonl
data/outputs/financial/{company_code}/{run_id}/pdf_highlights.json
data/outputs/financial/{company_code}/{run_id}/viewer_manifest.json
data/outputs/financial/{company_code}/{run_id}/evidence_viewer.html
data/outputs/financial/{company_code}/{run_id}/analysis_summary.md
data/outputs/financial/{company_code}/{run_id}/quality_report.json
data/outputs/financial/{company_code}/{run_id}/run_log.json
```

## 12.10 验收标准

- 每个基础数字有来源页码、表格、行列或坐标；
- 每个派生指标有公式和输入值；
- 每条分析结论可以追溯到计算过程；
- 右侧数据验证区是 PDF 阅读器，而不是普通文本面板；
- 点击基础数字时，PDF 阅读器能跳转到来源页并高亮来源区域；
- 点击派生指标时，能查看并切换多个输入值来源高亮；
- 高亮坐标随缩放保持准确；
- 无法精确定位的来源必须标记人工复核；
- 缺失或低置信度数据必须标记；
- 不依赖日历或电话会模块。

---

# 13. 功能三：电话会数据处理

## 13.1 功能目标

用户输入公司股票代码和电话会媒体文件后，系统生成带时间戳的逐字稿和可定位摘要。

## 13.2 输入

必填：

```text
company_code
media_path
```

可选：

```text
event_date
event_type
speaker_hints
language
```

## 13.3 Step-by-step

1. 解析公司。
2. 校验媒体文件。
3. 登记电话会和媒体文件。
4. 从视频中提取音频。
5. 统一音频格式。
6. 分段并保留原始时间偏移。
7. ASR 转写。
8. 说话人分离。
9. 说话人角色识别。
10. 生成原始逐字稿。
11. 清理逐字稿。
12. 识别会议结构。
13. 按主题分段。
14. 提取经营亮点。
15. 提取业绩指引。
16. 提取投资者问题。
17. 匹配管理层回答。
18. 生成可定位摘要。
19. 执行质量检查。
20. 保存结果。

## 13.4 输出

```text
data/outputs/calls/{company_code}/{call_id}/raw_transcript.jsonl
data/outputs/calls/{company_code}/{call_id}/clean_transcript.md
data/outputs/calls/{company_code}/{call_id}/speaker_segments.csv
data/outputs/calls/{company_code}/{call_id}/management_highlights.csv
data/outputs/calls/{company_code}/{call_id}/guidance_items.csv
data/outputs/calls/{company_code}/{call_id}/investor_qa.jsonl
data/outputs/calls/{company_code}/{call_id}/call_outline.json
data/outputs/calls/{company_code}/{call_id}/source_timestamps.json
data/outputs/calls/{company_code}/{call_id}/quality_report.json
data/outputs/calls/{company_code}/{call_id}/run_log.json
```

## 13.5 验收标准

- 必须由用户提供媒体文件；
- 每条摘要能定位到原始音视频时间戳；
- 低置信度内容有标记；
- 不虚构说话人；
- 不把模糊展望改写为承诺；
- 不与财报数据交叉验证；
- 不依赖日历或财务分析模块。

---

# 14. 贵州茅台端到端样例

## 14.1 用户输入

```text
company_code = 600519
```

用户提供报告文件：

```text
input_example/贵州茅台：贵州茅台2026年第一季度报告.pdf
```

注意：该文件名显示为 2026 年第一季度报告，因此在系统中应登记为 `report_type=q1`，而不是年报 `annual`。如果后续用户提供 2026 年年报，应另行登记。

## 14.2 路径解析

代码只允许使用：

```python
report_pdf_path = paths.get_input_example_path("贵州茅台：贵州茅台2026年第一季度报告.pdf")
```

禁止使用：

```python
report_pdf_path = r"<本机绝对路径>\input_example\贵州茅台：贵州茅台2026年第一季度报告.pdf"
```

## 14.3 公司解析

输入：

```json
{
  "company_code": "600519",
  "target_year": 2026
}
```

处理：

1. 在公司主数据 Excel 中查找 `Symbol=600519`。
2. 查询 2026 年记录。
3. 因当前 Excel 数据到 2025 年，回退使用 `EndDate=2025-12-31`。
4. 输出公司对象，并标记 `company_info_fallback=true`。

## 14.4 巨潮检索

读取：

```text
lookupfiles/web_address.txt
```

用以下关键词检索：

```text
600519 贵州茅台 2026 第一季度报告
```

输出应记录：

```json
{
  "company_code": "600519",
  "query_keyword": "600519 贵州茅台 2026 第一季度报告",
  "source_site": "巨潮资讯网",
  "source_url": "https://www.cninfo.com.cn/new/index.jsp",
  "manual_review_required": true
}
```

若自动化无法获取公告时间，必须提示人工在巨潮资讯网搜索并填入公告链接和发布时间。

## 14.5 财务分析样例运行命令

```bash
python scripts/run_financial.py \
  --company 600519 \
  --report-pdf "input_example/贵州茅台：贵州茅台2026年第一季度报告.pdf" \
  --report-year 2026 \
  --report-type q1
```

期望输出目录：

```text
data/outputs/financial/600519/{run_id}/
```

## 14.6 电话会样例

如果用户提供电话会录屏或音频，例如：

```text
data/raw_calls/600519/600519_2026Q1_call.mp4
```

运行：

```bash
python scripts/run_call.py \
  --company 600519 \
  --media "data/raw_calls/600519/600519_2026Q1_call.mp4" \
  --event-type earnings_call \
  --language zh-CN
```

若用户未提供媒体文件，电话会功能不得运行，也不得自动编造会议内容。

---

# 15. 中间结果与日志

每一步处理后都必须保存中间结果。

建议目录：

```text
data/processed/{feature}/{company_code}/{run_id}/{step_name}/
```

每个步骤至少保存：

```text
input_manifest.json
output_manifest.json
step_log.json
```

运行日志必须包含：

```text
run_id
company_code
feature
status
current_step
started_at
finished_at
warning_count
error_count
output_directory
```

状态枚举：

```text
pending
running
completed
completed_with_warnings
failed
```

---

# 16. 错误模型

建议至少定义：

```text
InvalidCompanyCodeError
CompanyNotFoundError
CompanyMasterDataUnavailableError
CompanyInfoFallbackWarning
PathConfigError
InputFileNotFoundError
UnsupportedFileFormatError
DataSourceUnavailableError
CninfoQueryError
ManualReviewRequiredError
ExtractionError
NormalizationError
EvidenceChainError
CalculationError
TranscriptionError
ExportError
```

错误处理原则：

- 错误信息必须指出具体步骤；
- 不得只返回“运行失败”；
- 已生成的中间结果应尽量保留；
- 单家公司失败不影响其他公司；
- 单项功能失败不影响其他功能；
- 数据缺失不得用猜测值填补；
- 外部网站不可用时应进入人工复核流程。

---

# 17. 测试与质量控制

## 17.1 路径测试

必须测试：

- `PROJECT_ROOT` 解析；
- 中文文件名；
- Windows 路径分隔符；
- 缺少配置项；
- 代码中不存在硬编码绝对路径。

建议检查命令：

```bash
python -m pytest tests/test_paths.py
```

并加入静态搜索：

```bash
rg "D:\\\\|C:\\\\" src scripts tests
```

## 17.2 公司解析测试

必须测试：

- `600519` 返回贵州茅台；
- `600519.SH` 可解析；
- 不存在股票代码报错；
- 2026 年回退 2025；
- 输出包含 fallback 字段；
- 三项功能得到相同公司对象。

## 17.3 日历测试

必须测试：

- 巨潮入口文件可读取；
- 自动检索失败时进入人工复核；
- 公告标题筛选；
- 报告类型标准化；
- 预约披露与实际披露区分；
- 不依赖财务和电话会模块。

## 17.4 财务分析测试

必须测试：

- PDF 文件登记；
- 报告类型识别；
- 表格抽取；
- 单位识别；
- 单位换算；
- `evidence_id` 生成；
- `trace_id` 生成；
- 证据链反查；
- `pdf_highlights.json` 生成；
- PDF 页码跳转目标正确；
- PDF 坐标高亮位置正确；
- 缩放后高亮不偏移；
- 派生指标可切换多个来源高亮；
- `evidence_viewer.html` 能打开并展示 PDF 页面；
- 无法精确定位的证据会标记人工复核；
- 不依赖日历和电话会模块。

## 17.5 电话会测试

必须测试：

- 未提供媒体文件时报错；
- 媒体格式校验；
- 时间戳连续性；
- 低置信度标记；
- 说话人编号稳定；
- 摘要来源定位；
- 不虚构说话人；
- 不依赖日历和财务分析模块。

---

# 18. 推荐开发顺序

## 第一阶段：路径与配置

实现：

- `configs/paths.yaml`
- `src/fintrace/shared/paths.py`
- 路径测试

验收：

- 改变项目根目录后业务代码不改；
- 代码中无绝对路径。

## 第二阶段：公司入口

实现：

- 公司主数据读取；
- 股票代码解析；
- 2026 回退 2025 规则；
- 标准公司对象；
- 公司解析测试。

## 第三阶段：日历功能

先实现巨潮入口读取和人工复核闭环，再尝试自动化检索。

## 第四阶段：财务分析功能

先用贵州茅台样例 PDF 跑通：

```text
PDF 登记
→ 页面与表格抽取
→ 指标识别
→ 证据链
→ PDF 高亮坐标
→ 右侧证据阅读器
→ 质量报告
```

## 第五阶段：电话会功能

等用户提供音视频后，再实现最小电话会闭环。

## 第六阶段：统一产品入口

只有三项功能都能独立运行后，才开发统一入口、订阅、任务队列和前端。

---

# 19. 每次让 AI 写代码的标准提示词

```text
请先阅读 FinancialReportAssistant_MANUAL_v3.md 和当前代码结构。

本次只实现【功能/步骤名称】。

请先回答：
1. 本次目标；
2. 本次非目标；
3. 事实来源；
4. 允许和禁止修改范围；
5. 验收证据。

约束：
- 所有路径必须通过 configs/paths.yaml 和 shared/paths.py 生成；
- 不得硬编码本机绝对路径；
- company_code 是唯一主键；
- 2026 公司基础信息缺失时回退 2025，并输出 fallback 标记；
- 三项功能不得产生业务依赖；
- 财务分析右侧数据验证区必须是 PDF 阅读器，点击证据后跳转并高亮 PDF 原文来源；
- 每一步中间结果必须落盘；
- 完成后必须运行测试和最小 demo。

请只修改与本功能直接相关的文件。
完成后输出修改文件、运行命令、测试结果、输出目录、风险和回滚方式。
```

---

# 20. MVP 总体验收标准

## 20.1 统一入口

- 三项功能均以 `company_code` 为必填输入；
- 股票代码能够唯一识别公司；
- 公司简称不作为主键；
- 所有输出包含股票代码；
- 三项功能共享相同公司对象；
- 2026 公司基础信息回退 2025 时有明确标记。

## 20.2 路径管理

- 所有代码路径均来自统一配置；
- 更换电脑只需修改一处项目根目录；
- 代码中无本机绝对路径；
- 中文文件名可正常读取。

## 20.3 日历功能

- 能读取巨潮资讯网入口；
- 能用股票代码检索或生成手工检索指引；
- 不虚构公告发布时间；
- 有独立脚本、输出、日志和测试；
- 不依赖另外两项功能。

## 20.4 财务分析功能

- 输入股票代码和 PDF 即可运行；
- 每个基础数字有原始证据；
- 每个派生结果有计算过程；
- 每条分析结论可以回溯到 PDF；
- 右侧数据验证区域以 PDF 阅读器形式展示原始财报；
- PDF 阅读器能够按 `evidence_id` 跳转页码并高亮数据来源；
- 高亮来源必须来自 PDF 坐标，不得只给截图或页码；
- 多来源派生指标可以切换查看各输入值的 PDF 高亮；
- 有独立脚本、输出、日志和测试；
- 不依赖另外两项功能。

## 20.5 电话会功能

- 必须由用户提供音视频文件；
- 能生成带时间戳的逐字稿；
- 能提取经营亮点、业绩指引和投资者问答；
- 每条提取内容可以回溯到原始音视频；
- 不执行财报数据交叉验证；
- 有独立脚本、输出、日志和测试；
- 不依赖另外两项功能。

## 20.6 可验证交付

- 每次任务有目标、非目标、事实源和边界；
- 每次修改有测试或明确未验证事项；
- 每次交付有证据、风险和回滚方式；
- 不通过跳过测试、硬编码或吞异常伪造完成；
- 长任务有检查点，可中断恢复。

---

# 21. 关键原则

- 股票代码是公司唯一标识。
- 公司基础信息来自项目内 Excel。
- 2026 公司基础信息暂无时完全参考 2025 数据，并显式标记。
- 报告发布时间来自巨潮资讯网检索或人工复核，不得猜测。
- 电话会音视频必须由用户提供。
- 所有代码路径必须是项目相对路径。
- 财务证据查看必须落到 PDF 阅读器中的可视高亮，而不是停留在文字说明。
- 三项功能先独立闭环，再统一入口。
- 每个基础数字必须能追溯来源。
- 每个派生指标必须保留公式和输入值。
- 每条电话会提取结果必须关联时间戳。
- 中间结果必须落盘。
- AI 每次只实现一个边界清晰的功能或步骤。
- 完成必须附证据。
