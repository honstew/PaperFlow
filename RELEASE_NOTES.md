# PaperFlow 0.1.0

发布日期：2026-10-27

## 内容

- M1–M6 主流程：TXT/Markdown 导入、AI 结构识别、图表/作者/基金、参考文献、LaTeX 编译、PDF 预览与导出。
- M5.5 可选 AI：参考文献解析、PDF 视觉审阅、白名单自动修复。
- M5.6 可选 AI 编译修复：编译日志 + TEX 最小 patch、打开 TEX、失败回滚。
- M6：最近项目、项目重新打开、Windows 便携版和安装包。

## 二进制

- 便携版：`binaries/PaperFlow-0.1.0-win64-portable.zip`
  - SHA256：`59b156ae0bb3c2ad68d05f505b68f6501b6af2e81b9753e1a41358a5eb472a7d`
- 安装包：`binaries/PaperFlow-0.1.0-setup.exe`
  - SHA256：`788a22af4c20591d4fb72e381d407911596b2a041775b26c5e691e320af3b5b7`

## 运行要求

- Windows 10/11 x64
- TeX Live 或 MiKTeX（含 ctex、xeCJK、biblatex-gb7714-2015、biber）
- 可选：DeepSeek/OpenAI 兼容 API Key（AI 功能关闭时不影响主流程）

## 验证

- `pytest`：80 passed
- `ruff check src tests`：通过
- 打包 exe 冒烟：exit 0
- 干净 Windows 安装/卸载验收：待执行

## 许可证

原创代码采用 MIT License，见 `LICENSE`。第三方组件许可证见 `THIRD_PARTY_NOTICES.md`。


