# Windows 打包

## 便携版

在项目根目录先安装构建依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
```

然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows.ps1
```

产物：

```text
dist\PaperFlow\PaperFlow.exe
dist\PaperFlow\
```

`dist\PaperFlow` 是完整便携目录，不能只复制单个 exe。

## 安装包（可选）

安装 Inno Setup 6 后，在项目根目录执行：

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\paperflow.iss
```

产物：

```text
dist\installer\PaperFlow-0.1.0-setup.exe
```

安装包使用当前用户目录，不要求管理员权限。

## 构建前检查

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m paperflow --smoke-test --no-auto-detect
```

## 干净机验收

1. 准备一台没有 Python、没有项目源码、没有缓存的 Windows 10/11 x64；
2. 安装 TeX Live（含 ctex、xeCJK、biblatex-gb7714-2015、biber）或 MiKTeX；
3. 只复制 `dist\PaperFlow`，双击 `PaperFlow.exe`；
4. 检查环境与 API 页能检测 TeX；
5. 导入 `examples/demo-paper.md`，完成 M2–M5，生成 PDF；
6. 关闭 AI 再重复一次，确认普通流程不受影响；
7. 打开最近项目，确认 M3–M5 状态能恢复；
8. 检查 `%APPDATA%\PaperFlow` 下的配置、日志和项目目录；
9. 确认日志里没有 API Key、正文或 PDF 图片；
10. 记录 Windows 版本、TeX 版本、字体和结果。

## 注意

- 当前 exe 未做代码签名，Windows SmartScreen 可能提示。
- 不把 `deepseek测试key.txt`、`.env`、项目 `content/` 或 `projects/` 打进安装包。
- 升级前先备份 `%APPDATA%\PaperFlow`。
- 如果杀毒软件误报，先核对构建机器和哈希，不要直接关闭防护。