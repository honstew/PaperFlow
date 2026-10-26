# Third-Party Notices

PaperFlow 的原创代码采用 MIT License。第三方依赖继续适用其各自的许可证；MIT License 不覆盖这些组件。

## Runtime dependencies

| 组件 | 用途 | 许可证 |
|---|---|---|
| PySide6 / Qt for Python | 桌面界面、Qt 运行库 | LGPL-3.0 / GPL-3.0 / Qt commercial |
| pypdfium2 / PDFium | PDF 页面渲染 | Apache-2.0 / BSD-3-Clause（PDFium） |
| openai-python | DeepSeek/OpenAI 兼容客户端 | Apache-2.0 |
| keyring | Windows 凭据管理器 | MIT |
| pydantic | 数据模型与校验 | MIT |
| platformdirs | 用户目录 | MIT |
| charset-normalizer | 文本编码识别 | MIT |
| markdown-it-py | Markdown 解析 | MIT |
| mdit-py-plugins | Markdown 插件 | MIT |
| Jinja2 | LaTeX 模板渲染 | BSD-3-Clause |
| Pillow | 图片与图标处理 | HPND |
| httpx | HTTP 客户端 | BSD-3-Clause |
| certifi | CA 证书 | MPL-2.0 |
| h11 | HTTP/1.1 | MIT |
| anyio | 异步 I/O | MIT |
| distro | 平台信息 | Apache-2.0 |
| sniffio | 异步库检测 | MIT |
| tqdm | 进度显示 | MPL-2.0 / MIT |
| typing-extensions | 类型向后兼容 | PSF-2.0 |
| annotated-types | 类型注解 | MIT |
| idna | 国际化域名 | BSD-3-Clause |
| packaging | 版本解析 | Apache-2.0 / BSD-2-Clause |
| pywin32-ctypes | Windows API 调用 | BSD-3-Clause |
| jaraco.classes / jaraco.context / jaraco.functools | keyring 依赖 | MIT |
| more-itertools | 迭代工具 | MIT |
| mdurl | URL 解析 | MIT |
| uc-micro-py | Unicode 数据 | MIT |
| linkify-it-py | 链接识别 | MIT |

## Build tools

- PyInstaller：GPL-2.0-or-later with bootloader exception；仅用于构建 Windows 可执行文件。
- Inno Setup：用于生成安装包；不随源码分发。
- Python 3.12：PSF License。

## External tools

PaperFlow 调用用户本机安装的 XeLaTeX、biber、TeX Live/MiKTeX。它们不随本项目分发，适用各自的许可证。TeX Live 通常包含多种自由软件许可证；分发或再打包前请自行核对。

## Qt / PySide6

Windows 便携版通过 PyInstaller 打包 PySide6/Qt 动态库。再分发时请遵守 LGPL-3.0 的要求，包括保留版权与许可证声明，并提供获取对应 Qt 源码的方式。若需要闭源商业分发，应使用 Qt 商业许可证或咨询法律意见。

## Full license texts

完整许可证文本以各依赖包内 `LICENSE`、`COPYING`、`METADATA` 或官方网站为准。发布前建议运行依赖许可证扫描，并把本文件与 `LICENSE` 一起放入发布包。