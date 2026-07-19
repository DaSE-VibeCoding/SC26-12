# FinancialReportAssistant

统一运行 DisclosureTimeAssistant 与 FinancialIndicatorsAssistant。用户只需输入一次 6 位股票代码，页面会并行启动两条分析路径，并通过页签分别查看结果。

## 启动

在 CMD 或 Windows“运行”中：

```bat
"C:\Users\Lenovo\AppData\Local\Programs\Python\Python313\python.exe" "D:\codeX\vibe_coding\SC26_12_v3\FinancialReportAssistant\start_app.py"
```

在 PowerShell 中需要在同一命令前加调用运算符 `&`：

```powershell
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python313\python.exe" "D:\codeX\vibe_coding\SC26_12_v3\FinancialReportAssistant\start_app.py"
```

首次启动会在项目目录创建 `.venv` 并安装 `requirements.txt` 中的 PDF 解析依赖。之后会直接复用该环境。

默认访问地址为 `http://127.0.0.1:8766/`，启动后自动打开浏览器。可追加 `--no-browser` 关闭自动打开，或用 `--port 0` 自动选择空闲端口。

## 两条并行路径

- `DisclosureTimeAssistant`：读取历史披露 Excel、行业与总资产资料，并按需补充巨潮披露预约数据；默认报告期为 2026 年一季报，可在查询区调整。
- `FinancialIndicatorsAssistant`：从巨潮下载并归档 2021—2025 年完整年度报告，提取 13 项关键财务指标，并提供 PDF 跳页与高亮证据。

任一路径失败不会取消另一条路径。页面顶部会分别显示两项任务的运行状态，成功结果仍可独立查看。

## 数据路径

披露时间助手默认从项目同级目录读取：

- `lookupfiles/DisclosureTime/DisclosureTime_History.xlsx`
- `lookupfiles/STK_LISTEDCOINFOANL_20200101_20251231.xlsx`

可通过 `DISCLOSURE_LOOKUP_ROOT`、`DISCLOSURE_HISTORY_FILE`、`DISCLOSURE_INDUSTRY_FILE`、`DISCLOSURE_TOTAL_ASSETS_FILE` 环境变量覆盖。

## 测试

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

测试覆盖双路并发 HTTP 请求、两个服务的健康状态、财务解析规则、静态资源、PDF 证据阅读器和前端并行/页签契约。
