# Terra Packager

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

[English](README.md) | 简体中文

## 简介

Terra Packager 是一个 **Python 命令行阅读包构建器**，可把《明日方舟》解包数据整理为 EPUB、PDF 和 TXT。它读取原始数据表与剧情脚本，提供：

- **六类内容导出**：主线剧情、插曲与支线、故事集、干员档案、干员密录、干员模组故事。
- **三种输出模式**：全部合成一本、按内容类型汇总、逐卷／逐条目分别输出。
- **五种语言与双语对照**：简中 `zh`、繁中 `tw`、英语 `en`、日语 `ja`、韩语 `ko`，支持任意两种语言组合。
- **完整分支阅读**：依次展示选项与分支，共同后续只输出一次；双语结构不同的场景分别保留各语言全文。
- **本地与远程数据**：读取本地资源库，或按需从 GitHub Raw 获取文件并缓存。
- **排版**：Typst A4 PDF、带嵌套目录和内嵌字体的 EPUB 3、UTF-8 TXT。
- **构建诊断**：环境检查、并发下载、目录索引和字体裁剪缓存。

[项目主页](https://github.com/Harry20120330/Terra-Packager) · [问题反馈](https://github.com/Harry20120330/Terra-Packager/issues)

## 项目结构

- `launch.py`：源码入口，与 `terra-packager` 共用同一套 CLI。
- `LICENSE` / `NOTICE`：项目许可证与第三方归属声明。
- `scripts/cli.py`：`list`、`info`、`build`、`doctor` 命令。
- `scripts/data_source.py`：各入口共用的本地数据检测、Git 克隆与下载重试。
- `scripts/repo_provider.py`：数据来源、卷目索引、远程下载与缓存。
- `scripts/avg_compiler.py` / `dag_linearizer.py`：AVG 解析、多语言对齐、分支编译与顺序阅读转换。
- `scripts/content_collector.py`：剧情、档案与模组正文收集。
- `scripts/packager.py` / `*_builder.py`：PDF、EPUB、TXT 和 ZIP 构建。
- `scripts/templates/` / `assets/`：排版模板、拉丁字体及字体许可证。
- `scripts/doctor.py` / `runtime.py` / `benchmark.py`：环境检查、缓存写入、计时和合成基准。
- [`.github/workflows/checks.yml`](.github/workflows/checks.yml)：Windows／Linux 自动检查。

## 快速开始

### 前置条件

- **Python 3.10+**；安装时自动安装运行依赖 `fonttools`。
- **TXT**：无需 Typst 或排版字体。
- **PDF / EPUB**：需要 Typst，推荐 **0.15.1**，以及所需语言的 Noto Serif CJK 常规／粗体字体。EPUB 也使用 Typst 生成封面。
- **数据**：可使用本地资源库，或在联网环境按需获取。项目不附带真实游戏语料。

### 安装

在包含 `pyproject.toml` 的项目源码目录执行：

```sh
python -m venv .venv
```

激活虚拟环境，然后安装：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```sh
# Linux / macOS
source .venv/bin/activate
```

```sh
python -m pip install .
terra-packager --help
```

### 使用

`build` 默认导出全部六类内容，只选择格式、语言和输出类型，成品写入当前目录下的 `output/`：

```sh
# 一本完整合集
terra-packager build -f epub -l zh --output-mode combined

# 六类内容各一本
terra-packager build -f pdf,epub,txt -l zh --output-mode by-type

# 逐卷／逐条目输出（默认模式）
terra-packager build -f txt -l zh --output-mode separate

# 双语属于语言设置
terra-packager build -f epub -l zh -s en --output-mode combined
```

在源码目录可用 `python launch.py` 或 `python -m scripts` 代替 `terra-packager`。默认格式为 `pdf,epub,txt`、语言为 `zh`、输出类型为 `separate`。不指定选卷条件也会构建全部内容。

| `--output-mode` | 内容组织 | 六类齐全、三种格式时 |
| --- | --- | --- |
| `combined` | 全部合成一本 | 3 个文件 |
| `by-type` | 每种内容类型一本 | 18 个文件 |
| `separate`（默认） | 剧情／密录逐卷，档案逐干员，模组逐条目 | 每个单位 3 个文件 |

逐卷输出放入 `output/mainline/`、`sidestory/`、`ministory/`、`operator-profile/`、`operator-record/`、`operator-module/`，避免不同分类的同名文件覆盖。主线卷号从 `000` 开始，插曲与支线和故事集各自从 `001` 开始；密录没有卷号，标题为“干员名 · 密录名”，文件名附稳定标识以区分同名密录。

本版本删除 `build` 的旧选卷、范围、分类、内容筛选、`--all`、模式别名、输出路径、ZIP、下载、数据源及其他高级参数。旧命令请改成上述三类设置；源码入口和安装后的 CLI 行为一致。

### 数据来源与查看命令

`build` 自动检测当前目录的 `data/ArknightsGamedata`；没有本地数据时，从 GitHub Raw 按需获取并缓存。准备本地数据：

```sh
git clone --depth 1 https://github.com/ArknightsAssets/ArknightsGamedata.git data/ArknightsGamedata
terra-packager build -f txt --output-mode combined
```

自动检测支持 `{cn,tw,en,jp,kr}/gamedata`、`{zh_CN,zh_TW,en_US,ja_JP,ko_KR}/gamedata`、裸 `gamedata` 或直接包含 `excel` 的布局。构建六类内容需要完整的剧情目录、剧情脚本、角色表、档案表和模组表。

`list`、`info`、`doctor` 保留查看与诊断用途，数据源参数放在子命令后：

```sh
terra-packager list --category mainline
terra-packager list --category record --search 克洛丝
terra-packager info main_0 --lang en
terra-packager list --repo-dir data/ArknightsGamedata --limit 0
terra-packager list --download --category mainline
terra-packager doctor -l zh -f epub
```

`info` 推荐使用唯一的 `groupId`。独立编号后，同一个数字可能属于多个分类；输入重号时会列出候选 ID，不会默认选中某一类。密录可用 `story_kroos_set_1` 等 ID 查看。

查看命令仍支持 `--source arknights-assets/kengxxiao`、`--repo-url`、`--repo-dir`、`--yostar-dir`、`--cache-dir`、`--no-cache` 和显式 `--download`。`--download` 只在缺少本地数据时浅克隆；帮助和 `doctor` 不下载。克隆使用 HTTP/1.1 并最多重试三次，不修改全局 Git 配置，失败时保留已有目录。

### EPUB 与 Kindle

EPUB 阅读顺序为“纯图片封面 → 独立目录 → 主线剧情 → 其余内容”。EPUB 3 landmarks 和旧版 guide 分别指向封面、目录和正文。

合成一本 EPUB 时，目录页先列出可直达正文的简明分类索引，再列详细目录。干员密录和干员模组按“分类 → 干员名 → 密录名／模组名”分组。密录的各场剧情保留在正文中。

使用 boko 转 AZW3 的检查基准为 0.6.0：

```sh
boko convert output/泰拉文库全内容合集.epub book.azw3
```

boko 的 AZW3 导出将正文入口写为 `text`，其默认“开始”入口可能指向书首；删除封面跳转页后，通过独立目录选择“主线剧情”阅读。页码／位置值由转换器和阅读器生成，验收关注目录目标与正文实际顺序，不使用 PDF 页码填充 EPUB 页码。

## 注意事项

- **离线条件。** 检测到本地数据后不会为缺失数据访问网络。PDF／EPUB 完全离线还需提前准备 Typst 和字体；wheel 不附带平台专属 Typst。
- **双语对齐。** 相同分支结构内按原文顺序配对，额外段落保留；结构无法可靠对齐时按主语言、次语言分别输出完整场景并标记，不能保证逐句语义对应。
- **分支语法。** 单独分支之前的全选项条件会保留选项作用域。嵌套选项可通过子选项值的合集汇合，多个选项也可共享一个值；选项文本全部保留，共享正文只输出一次。
- **纯视频场景。** 只有视频播放而没有可打印正文的 AVG 脚本会自动跳过，显示提示并计入汇总。文件缺失、空文件，以及正文在编译中丢失仍按原规则报错；不会生成完全空白的读物。
- **不一致的分支数据。** 上游条件引用无法解析，或选项文本多于分支值时，会显示脚本和语言的警告。该语言的全部正文和选项按原文顺序保留，不推测分支连接，并计入构建汇总。未结束的多行对白会在下一条普通对白之前输出。
- **缺译与缺失。** 双语剧情保留现有语言；档案／模组可显示原文和缺译标记。缺失或空内容报错，损坏 JSON、空选项值或网络故障也会报错；全空仍失败。
- **成品保留。** 每本书在临时目录完成所选格式后再替换正式文件，渲染失败保留已有成品和此前完成的书。
- **内存与并发。** 全库聚合占用更多内存。目录索引保留在内存中；下载默认最多 4 个并发任务，字体裁剪最多 2 个，整本书顺序渲染。
- **缓存与错误提示。** 资源按源配置及实际 URL 隔离并原子写入，字体子集可复用，旧缓存不自动迁移。远程临时故障（包括 HTTP 响应正文中途断开）每源最多尝试三次；404 尝试备用源，网络故障不会作为缺少剧情处理。

## 配置项

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `TERRA_CACHE_DIR` | `~/.cache/terra-packager` | 资源、字体裁剪及下载的 Typst 缓存根目录 |
| `--cache-dir DIR` | 查看命令使用上述目录 | 只覆盖资源缓存，字体和 Typst 仍使用环境变量目录 |
| `TERRA_TYPST_BIN` | 自动查找 | 本地 Typst 可执行文件；无效配置直接报错 |
| `TERRA_NOTO_FONT_DIR` | 系统字体查找 | Noto 字体目录；EPUB 默认查找 Linux 系统 Noto TTC |
| `--no-cache` | 关闭 | 绕过持久资源缓存读取，本次仍复用已获取数据并写入缓存 |

项目不自带 Typst。依次查找显式配置、系统 PATH、用户缓存，在构建 PDF／EPUB 需要时自动下载 0.15.1。自动下载支持 Linux／macOS 的 x86-64 和 ARM64，以及 Windows 的 x86-64；其他平台需通过 `TERRA_TYPST_BIN` 指定兼容的可执行文件。字体支持 `NotoSerifCJK-{Regular,Bold}.ttc`，或 `NotoSerifCJKsc/tc/jp/kr-{Regular,Bold}.otf/.ttf`、`NotoSerifSC/TC/JP/KR-{Regular,Bold}.otf/.ttf`。PDF／封面按家族名称查找，重命名文件不能更改家族；当前英文模板也配置 `Noto Serif CJK SC` 回退字体。

Ubuntu / Debian 可用 `sudo apt install fonts-noto-cjk`。Windows 示例：

```powershell
$env:TERRA_NOTO_FONT_DIR = "C:\fonts\noto"
$env:TERRA_TYPST_BIN = "C:\tools\typst.exe"
terra-packager doctor -l zh -f pdf,epub,txt
```

## 常见问题

- **找不到 `terra-packager`：** 激活安装项目时使用的虚拟环境；源码目录也可运行 `python -m scripts --help`。
- **提示不识别旧构建参数：** `build` 只支持格式、语言和输出类型；需要下载数据时使用 `terra-packager list --download`，再运行 `build`。安装后的命令尚未更新时，在已激活环境运行 `python -m pip install --upgrade .`。
- **旧版出现 `Unscoped predicate references` / `Unknown predicate references`：** 更新整个源码目录，包括 `launch.py` 和 `scripts/`，再在已激活的环境运行 `python -m pip install --upgrade .`。1.0.0 支持全选项条件、子选项合集汇合及重复选项值，保留多余选项文本，并修正被普通对白打断的多行正文顺序。
- **本地全库构建在 `act13mini` 停止：** 部分 ArknightsAssets 数据版本有该活动目录表，但缺少六个中文剧情文件。可提前从 Kengxxiao 源补齐，或使用完整本地资源库。本地构建不会自动联网补缺。
- **Noto 字体找不到／Typst 下载失败：** 运行 `doctor`，核对字体常规与粗体文件和字体家族名称；无法自动下载时用 `TERRA_TYPST_BIN` 指定本地 Typst。TXT 可独立运行。
- **本地仓库缺少内容：** 检查语言目录和全部六类内容所需的数据表与脚本，补齐缺失文件后重新构建。
- **提示下载失败或超时：** 检查 GitHub Raw 网络、源地址和缓存目录权限，或改用本地资源库；网络失败会明确报错。
- **Git 克隆出现 TLS 中断（`GnuTLS recv error (-110)`）：** HTTPS 克隆现在会重试，且不修改全局 Git 配置。仍失败时检查网络或代理，或用 `terra-packager list --source arknights-assets` 按需获取文件。旧版失败克隆若留下非空目录，请改用新的 `--data-dir`，或检查目录后自行清理。
- **双语场景分成两段：** 原始结构无法可靠对齐，工具保留各语言完整版本；这是明确标记的回退行为。
- **全库构建耗时长：** 优先使用完整本地数据；只需要文字时选择 `-f txt`，避免排版和字体裁剪开销。

## 开发与打包

```sh
python -m pip install ".[dev]" setuptools wheel
python -m build
python -m scripts.benchmark --output tmp/benchmark.json
```

Windows／Linux 工作流在 Python 3.10／3.12 上构建安装包并检查安装后的 CLI，不下载游戏数据。合成基准测目录查询和字体缓存复用，不等于真实上游全库压测。

`.venv/`、`build/`、`dist/`、`*.egg-info/` 和 `tmp/` 属于本地环境或构建产物，已排除在版本控制之外。分发清单也排除测试、随附可执行文件、虚拟环境和临时输出。

## 许可证

本项目仓库采用 **Apache License, Version 2.0**，完整文本见 [LICENSE](LICENSE)，第三方归属声明见 [NOTICE](NOTICE)。附带字体依 SIL Open Font License 授权，许可证文本位于 `scripts/assets/licenses/`。

感谢 ArknightsAssets、Kengxxiao、Typst 和 fonttools 项目。《明日方舟》的剧情、角色及游戏内容属于其权利人，项目代码和字体许可证不授予游戏内容的使用权。
