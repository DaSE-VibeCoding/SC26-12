# FinTrace 财报分析助手

DaSE 2026 暑期学校 SC26-12 小组项目。

FinTrace 是一个以股票代码为唯一公司标识、分析结果可追溯到原始来源的本地后端。
项目不使用数据库；原始资料、中间结果、运行日志和最终输出统一保存在 `data/`。

当前后端 MVP 已实现统一路径、本地文件存储、公司解析、日历人工导入、财报抽取、
财务证据链和只读查询 API。语音转文字与电话会模块不在当前范围内。

## 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

解析公司并把运行结果写入 `data/`：

```bash
python scripts/resolve_company.py --company 600519 --target-year 2026
```

从 `lookupfiles/web_address.txt` 指定的巨潮资讯网查询目标年份发布的正式中文年度报告，
排除摘要、半年度报告和英文版，并记录发布时间：

```bash
python scripts/run_calendar.py \
  --company 600519 \
  --target-year 2026
```

网络查询无结果时，系统不会猜测日期，而是在输出目录生成巨潮资讯网人工检索指引。
也可以使用 `--manual-file` 导入人工复核后的 CSV 或 JSON。

分析样例财报：

```bash
python scripts/run_financial.py \
  --company 600519 \
  --report-pdf "input_example/贵州茅台：贵州茅台2026年第一季度报告.pdf" \
  --report-year 2026 \
  --report-type q1
```

启动本地只读 API：

```bash
fintrace-api
```

OpenAPI 文档位于 `http://127.0.0.1:8000/docs`。API 只读取 `data/` 中的 JSON、
JSONL 和 CSV 文件，不需要数据库服务。

所有路径均由 `configs/paths.yaml` 和 `PROJECT_ROOT` 解析。除非需要从其他目录运行项目，通常无需设置 `PROJECT_ROOT`。
