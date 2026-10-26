# PaperFlow

PaperFlow 是一个面向 Windows 的本地论文学术排版工具。当前仓库已完成 **M1–M6** 主流程，并提供 M5.5 可选 AI 模块。

## M1 已实现

- PySide6 桌面主窗口与 8 步流程框架
- OpenAI 兼容 API 配置：Base URL、API Key、模型、代理
- DeepSeek 默认配置：`https://api.deepseek.com` + `deepseek-flash`
- API Key 保存到 Windows 凭据管理器；不可用时仅保存在内存
- 真实的 XeLaTeX 环境检测：
  - `xelatex --version`
  - `latexmk`
  - `kpsewhich` 宏包检查（ctex、xeCJK、biblatex-gb7714-2015 等）
  - Windows 中文字体检查
  - `biber`
  - 用一份最小中文文档实际编译，检查 PDF 是否生成
- 缺少环境时的 TeX Live（推荐，含清华镜像）/ MiKTeX 安装引导
- 日志写入 `%APPDATA%\PaperFlow\logs\paperflow.log`，自动脱敏 Key

## M2 已实现

- TXT 导入：UTF-8 / GB18030 编码识别、空行分段、行号、标题与图/表题注规则、Tab 表格
- Markdown 导入：标题、段落、列表、代码块、GFM 管道表格、本地图片、`$...$` / `$$...$$` 公式
- 带稳定 ID 的 `DocumentIR`：块 ID、来源行号、`runs`、图表占位
- 项目工作区：复制源文件到 `source/`，图片复制到 `assets/figures/`，保存 `content/manuscript.json`
- 导入页：拖拽/选择文件、后台解析、KPI 摘要、待处理项、内容块表格、图表占位状态
- 示例文件：`examples/demo-paper.md`、`examples/demo-paper.txt` 与示例图片
- 明确拒绝 DOCX/DOC/PDF，并提示改用 TXT/Markdown

详细交付说明：[docs/M2-交付说明.md](docs/M2-交付说明.md)

## M3 已实现

- DeepSeek/OpenAI 兼容结构识别，默认 `deepseek-flash`，关闭 thinking
- JSON Output、Pydantic 校验、缺块/重复块覆盖检查、空内容/截断/解析失败重试
- 自动提取题名、作者、单位、摘要、关键词、章节、图表题和参考文献角色
- 本地规则回退：无 Key 或不想联网时仍可生成结构基线
- 结构校对页：章节树、内容块表、角色/标题级别下拉修改、置信度
- 保存 `content/structure.json` 与 `content/manuscript-structured.json`
- 真实 DeepSeek 测试：29 块、6 章节、0 待确认，输入 2248 / 输出 906 tokens
- 日志不记录正文和 Key；真实测试 Key 未写入程序或项目

详细交付说明：[docs/M3-交付说明.md](docs/M3-交付说明.md)

## M4 已实现

- 图表管理：图片预览、上传/替换、移除、图题、宽度比例、跨栏、插入锚点
- 表格编辑：增删行列、CSV/Excel 粘贴、表题/表注、跨栏、锚点
- 作者与基金：多作者、多单位、通信作者、邮箱、作者简介、基金开关与多项目
- 正文候选自动预填：题名、摘要、关键词、作者、单位、基金、作者简介
- 来源标签：正文预填 / AI 预填 / 手动修改 / 未填写
- 正文/表单冲突：字段级提示、采用正文、保留表单、基金关闭二次确认
- `consumed_block_ids`：已吸收的正文块在生成时跳过，避免重复输出
- 保存 `content/assets.json`、`content/metadata.json`、`content/m4-state.json`
- 真实测试 Key 未写入程序、项目或日志

详细交付说明：[docs/M4-交付说明.md](docs/M4-交付说明.md)

## M5 已实现

- 参考文献：本地规则解析、逐条编辑/确认、生成 `refs.bib`
- 版式设置：国标通用模板、单/双栏、页边距、行距、字号
- 确定性 LaTeX 渲染：题名、作者/单位、摘要、章节、图片、三线表、公式
- 引言不编号；章节自动编号；已吸收正文块不重复输出
- XeLaTeX + biber 编译：`output/main.tex` → `output/build/main.pdf`
- PDF 预览：翻页、按预览区宽度缩放
- ZIP 导出：TEX、PDF、BIB、JSON、图片
- AI 不生成最终 `.tex`；M5 参考文献首版为本地规则 + 人工修正
- 真实示例编译：3 页，约 9.4 秒

详细交付说明：[docs/M5-交付说明.md](docs/M5-交付说明.md)

## M5.5 可选 AI 模块

- 默认关闭；没有 API Key 时 AI 按钮禁用，M5 原有流程不受影响
- AI 参考文献解析：只发送参考文献原文，结果仍需逐条确认
- AI PDF 视觉审阅：渲染页面图片，最多 20 页，返回版式 findings
- 选中 findings 可应用**白名单修复**：图片宽度/跨栏、表格跨栏、标题前分页
- 修改写入 `content/overrides.json`，重新编译；可对比前后 PDF 并回滚
- AI 不直接修改或覆盖最终 `main.tex`
- 每次调用前显式确认；不把 PDF 图片或正文写入日志
- 提示词在 `src/paperflow/llm/ai_prompts.py`
- 编译失败可用 **AI 修复编译错误**：发送日志 + TEX，返回最小 patch，应用前备份、失败回滚
- 生成导出页提供 **打开 TEX**，用本机默认程序编辑 `main.tex`
- AI 关闭时仍可正常生成 PDF、导出 ZIP

详细说明：[docs/M5.5-AI模块.md](docs/M5.5-AI模块.md)  
编译修复：[docs/M5.6-AI编译修复.md](docs/M5.6-AI编译修复.md)

## M6 已实现

- 最近项目列表：论文名、更新时间、项目路径
- 项目重新打开：恢复 M2–M5 状态与 `overrides.json`
- 缺失/移动项目自动提示并从最近列表移除
- Windows 便携版构建脚本与 PyInstaller spec
- Inno Setup 安装包（当前用户安装，不要求管理员）
- 已生成 `dist\installer\PaperFlow-0.1.0-setup.exe`
- 干净机验收清单与数据目录说明
- 应用图标

构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows.ps1
```

产物：`dist\PaperFlow\PaperFlow.exe`（已实际构建，打包 exe 冒烟通过）。

开源发布目录：`release\PaperFlow-0.1.0\`，包含 MIT 源码、便携版 ZIP、安装包和校验文件。

详细说明：[docs/M6-交付说明.md](docs/M6-交付说明.md)

## 运行

要求：Windows 10/11 x64、Python 3.12、已安装或准备安装 XeLaTeX（推荐 TeX Live，也可用 MiKTeX）。

```powershell
git clone https://github.com/<你的账号>/PaperFlow.git
cd PaperFlow
.\run.bat
```

已经拿到源码包的话，进入源码目录直接运行 `.\run.bat` 即可。

也可以直接双击 `run.bat`。它使用 `-ExecutionPolicy Bypass` 启动 `run.ps1`，避免 Windows 默认执行策略拦截本地脚本。

首次运行会创建 `.venv`、安装 `uv` 和项目依赖；之后启动不再重复安装。

如果坚持直接运行 PowerShell 脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

M1 主界面：

![M1 主界面](docs/m1-main-window.png)

M2 导入页：

![M2 导入页](docs/m2-import-page.png)

试用 M2：

1. 启动后点击左侧“导入论文”；
2. 选择 `examples/demo-paper.md`；
3. 查看内容块、图片占位、表格与待处理项；
4. 项目文件位于 `%APPDATA%\PaperFlow\projects\`。

M3 结构校对页：

![M3 结构校对](docs/m3-structure-page.png)

试用 M3：

1. 先在“环境与 API”填写并测试 Key；
2. 导入 `examples/demo-paper.md`；
3. 点击“结构校对”；
4. 点击“AI 识别结构”或“使用本地规则”；
5. 修改角色/级别，点击“保存结构”。

M4 图表管理：

![M4 图表管理](docs/m4-assets-page.png)

M4 作者与基金：

![M4 作者信息](docs/m4-metadata-page.png)

M4 冲突确认：

![M4 冲突确认](docs/m4-conflict.png)

试用 M4：

1. 完成 M3 结构识别；
2. 点击“图表管理”，上传缺失图片或编辑表格；
3. 点击“作者信息”，检查预填内容与冲突；
4. 保存后查看项目 `content/assets.json`、`metadata.json`、`m4-state.json`。

M5 参考文献：

![M5 参考文献](docs/m5-references-page.png)

M5 版式设置：

![M5 版式设置](docs/m5-layout-page.png)

M5 生成与导出：

![M5 生成与导出](docs/m5-build-page.png)

试用 M5：

1. 完成 M4 作者信息；
2. 点击“参考文献”，确认条目并保存；
3. 点击“版式设置”，选择单/双栏并保存；
4. 点击“生成导出”，编译 PDF，翻页预览，或导出 ZIP。

首次运行会创建 `.venv` 并安装依赖。之后可以：

```powershell
.\.venv\Scripts\python.exe -m paperflow
```

调试日志：

```powershell
.\run.bat --debug
```

不自动检测环境（用于 UI 调试）：

```powershell
.\run.bat --no-auto-detect
```

无界面冒烟测试（启动窗口后自动退出）：

```powershell
.\.venv\Scripts\python.exe -m paperflow --smoke-test --no-auto-detect
```

## 开发

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## 安全约定

- API Key 不写入 `settings.json`、日志、项目文件或导出包。
- 本地测试 Key 文件已加入 `.gitignore`，只从环境变量读取，不写入源码。
- 只发送你主动触发测试/识别时的最小请求。
- 不启用 LaTeX `shell-escape`；不执行用户文本中的任意命令。
- 不静默安装 TeX 发行版，不自行提权。

## 当前限制

- M6 已实现最近项目、项目重开与打包脚本；干净机验收仍需在真实干净 Windows 上执行。
- 当前 exe 未做代码签名；安装包已生成，重建时需本机安装 Inno Setup。
- M3 首版一次请求处理全文；超过约 12 万字符会提示拆分，尚未分块识别。
- AI 可能把正文中的“图1”误判为图题，需要在结构校对页人工修改。
- M4 图片只支持 PNG/JPG/JPEG；不做裁剪、DPI、PDF/SVG/EMF 转换。
- M4 表格不支持合并单元格、嵌套表和单元格富文本；复杂表格建议按图片处理。
- 冲突检测是字段/列表级；“采用正文/保留表单”是整组操作，暂不支持逐作者 diff。
- M5 参考文献默认本地规则解析；AI 条目解析是可选模块，需 Key 并显式确认。
- M5.5 自动修复只覆盖白名单参数；正文、作者、参考文献、数字和公式永不自动改。
- AI 视觉审阅可能误判版式；它是辅助检查，不替代人工终检。
- 正文引用只做简单 `[n]` → `\cite{key}` 映射；复杂引用仍需后补。
- 首版只做“国标通用”模板；未提供学校专用模板、封面和模板编辑器。
- M5 表格不支持跨页长表、合并单元格；公式只支持简单 LaTeX 命令。
- PDF 预览只有翻页和按宽度缩放，没有缩放百分比、打印和批注。
- 输入格式为 TXT / Markdown；**不支持 DOCX/DOC、PDF（含扫描版）作为正文输入**。
- Markdown 表格不支持合并单元格；远程图片不自动下载；原始 HTML 只保留为待处理块。
- 图片路径必须位于源 Markdown 所在目录内，超出范围的路径会被拒绝。
- 最近项目记录绝对路径；移动项目目录后需要重新导入。

## License

PaperFlow 原创代码采用 **MIT License**，见 [LICENSE](LICENSE)。

第三方依赖（PySide6/Qt、pypdfium2/PDFium、openai-python、Jinja2 等）继续适用其各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。MIT License 不覆盖第三方组件。

## 目录

```text
src/paperflow/
  core/       配置、API、密钥、环境检测、DocumentIR、项目工作区、结构/元数据、
              参考文献、版式、LaTeX 渲染与编译
  ingest/     TXT / Markdown 解析
  llm/        DeepSeek/OpenAI 兼容结构识别、提示词、JSON 解析
  ui/         PySide6 界面、图表、作者基金、参考文献、版式、生成导出
  app.py      应用入口
  main.py     console entry
examples/     可直接导入的示例 TXT / Markdown
tests/        单元测试、文档解析测试与 UI 冒烟测试
docs/         设计文档、交付说明与截图
参考论文例子/  用户提供的参考论文（不修改）
```