# Terra Packager

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

English | [简体中文](README.zh.md)

## Introduction

Terra Packager is a **Python command-line reading-package builder** that turns unpacked Arknights game data into EPUB, PDF, and TXT books. It reads source tables and story scripts and provides:

- **Six content types:** main stories, side stories, vignettes, operator profiles, operator records, and module stories.
- **Three output modes:** one combined collection, a book per content type, or separate books per volume or entry.
- **Five languages and bilingual editions:** Simplified Chinese `zh`, Traditional Chinese `tw`, English `en`, Japanese `ja`, and Korean `ko`, with any two languages supported together.
- **Complete branch reading:** choices and branches appear sequentially, with shared continuations shown once. Incompatible bilingual structures retain each language's complete scene separately.
- **Local and remote sources:** read a local game-data checkout or fetch required files from GitHub Raw and cache them.
- **Publication and archives:** Typst A4 PDFs, EPUB 3 with nested navigation and embedded fonts, UTF-8 TXT, and optional ZIP bundles.
- **Build diagnostics:** environment checks, concurrent downloads, catalog indexes, cached font subsets, and stage timing reports.

[Repository](https://github.com/Harry20120330/Terra-Packager) · [Issues](https://github.com/Harry20120330/Terra-Packager/issues)

## Project Structure

- `launch.py`: source launcher; detects local data and clones the data repository when explicitly requested.
- `LICENSE` / `NOTICE`: the project license and third-party attribution notices.
- `scripts/cli.py`: the `list`, `info`, `build`, and `doctor` commands.
- `scripts/repo_provider.py`: sources, catalog indexes, remote downloads, and caching.
- `scripts/avg_compiler.py` / `dag_linearizer.py`: AVG parsing, multilingual alignment, branch compilation, and sequential reading.
- `scripts/content_collector.py`: story, profile, and module prose collection.
- `scripts/packager.py` / `*_builder.py`: PDF, EPUB, TXT, and ZIP generation.
- `scripts/templates/` / `assets/`: publication templates, Latin fonts, and font licenses.
- `scripts/doctor.py` / `runtime.py` / `benchmark.py`: diagnostics, atomic cache writes, timing, and synthetic benchmarks.
- [`.github/workflows/checks.yml`](.github/workflows/checks.yml): Windows and Linux checks.

## Quick Start

### Prerequisites

- **Python 3.10+**. Installation includes the runtime dependency `fonttools`.
- **TXT:** no Typst or publication fonts required.
- **PDF / EPUB:** Typst, preferably **0.15.1**, and regular/bold Noto Serif CJK fonts for the required languages. EPUB also uses Typst to render its cover.
- **Data:** a local checkout or network access for on-demand retrieval. No actual game prose is bundled.

### Installation

Run these commands from the project source directory containing `pyproject.toml`:

```sh
python -m venv .venv
```

Activate the environment, then install:

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

### Usage

```sh
# Browse main stories; omitted --repo-dir enables remote retrieval
terra-packager list --category mainline

# Inspect a volume's titles and script list
terra-packager info main_0 --lang en

# Start with TXT to try the complete pipeline
terra-packager build -v main_0 -l zh -f txt -o output

# Generate a bilingual edition in all three formats, plus ZIP
terra-packager build -v main_0 -l zh -s en -f pdf,epub,txt -o output --zip main-0.zip
```

From the source directory, `python -m scripts` can replace `terra-packager`. Defaults are `pdf,epub,txt`, language `zh`, and directory `output`.

### Data Sources

| Repository | Local language directories | Remote selector |
| --- | --- | --- |
| [ArknightsAssets/ArknightsGamedata](https://github.com/ArknightsAssets/ArknightsGamedata) | `{cn,tw,en,jp,kr}/gamedata` | `--source arknights-assets` (default) |
| [Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData) | `zh_CN/gamedata` | `--source kengxxiao` |
| [Kengxxiao/ArknightsGameData_YoStar](https://github.com/Kengxxiao/ArknightsGameData_YoStar) | `{zh_TW,en_US,ja_JP,ko_KR}/gamedata` | Kengxxiao international source |

```sh
git clone --depth 1 https://github.com/ArknightsAssets/ArknightsGamedata.git data/ArknightsGamedata
terra-packager build --repo-dir data/ArknightsGamedata -v main_0 -f txt -o output
```

Use `--yostar-dir DIR` for a separate Kengxxiao international checkout. Bare Chinese `gamedata` directories and directories containing `excel` are also accepted. `--repo-url URL` selects a Raw root following the ArknightsAssets layout, such as `https://raw.githubusercontent.com/OWNER/REPO/BRANCH`, rather than a repository webpage.

The source launcher checks `data/ArknightsGamedata` by default. Without local data it uses on-demand retrieval; `--download` explicitly requests a clone, trying SSH before HTTPS by default:

```sh
python launch.py --help
python launch.py --download list --category mainline
python launch.py --data-dir data/ArknightsGamedata build -v main_0 -f txt
```

Explicit `--repo-dir`, `--source`, and `--repo-url` override automatic detection. Help and `doctor` do not download data.

### Output Modes and Selection

| `--output-mode` | Organization | All six types and three formats |
| --- | --- | --- |
| `combined` | One collection of all selected content | 3 files |
| `by-type` | One book per content type | 18 files |
| `separate` (default) | Stories/records per volume, profiles per operator, modules per entry | 3 files per unit |

| `--content-types` | Content |
| --- | --- |
| `mainline` / `sidestory` / `ministory` | Main stories / side stories / vignettes |
| `operator-profile` / `operator-record` / `operator-module` | Profiles / records / modules |

```sh
# One complete collection
terra-packager build --repo-dir data/ArknightsGamedata --output-mode combined -f txt

# A collection per type
terra-packager build --repo-dir data/ArknightsGamedata --output-mode by-type -f txt

# Separate books for all volumes and entries
terra-packager build --repo-dir data/ArknightsGamedata --all -f txt

# Combine selected volumes; --range 001-005 is also supported
terra-packager build --output-mode combined -v main_0,main_1 -f txt

# Profiles and modules only
terra-packager build --content-types operator-profile operator-module -f epub
```

- Aggregate modes select all six types when no selectors are provided. Default `separate` needs a volume, range, category, content type, or `--all`.
- `--category mainline/sidestory/ministory/operator` selects stories; `operator` means operator records. `--volume` accepts a number, `groupId`, or title. Numbers depend on the current data; use `groupId` in persistent configurations.
- Story selectors combined with `--content-types` restrict story volumes only; explicitly selected profiles/modules still include all entries of those types. `--all` may be narrowed by content types but cannot be combined with volume/range/category selectors.
- Compatibility aliases `--mode single/category/separate` map to the three modes and cannot be combined with `--output-mode`. `--category archive/module/record` selects profiles/modules/records; `archive` and `module` cannot be combined with volumes, ranges, or `--all`.

## Notes

- **Offline requirements.** `--repo-dir` never fetches missing data from the network. Fully offline PDF/EPUB builds also need Typst and fonts prepared beforehand; wheels contain no platform-specific Typst executable.
- **Bilingual alignment.** Matching branch intervals pair prose in source order and retain extra paragraphs. Incompatible structures output complete primary and secondary scenes separately with a notice; sentence-level semantic alignment is not guaranteed.
- **Missing translations/content.** Bilingual stories retain available languages; profiles/modules may show original prose with a missing-translation marker. Missing or empty requested content fails by default. `--skip-missing` skips it but does not suppress corrupt JSON, invalid branch references, or network failures. An entirely empty result still fails.
- **Finished files.** All requested formats for a book are built in a temporary directory before replacing final files. Renderer failures preserve existing outputs and earlier completed books. `--zip` must be a `.zip` filename inside the output directory.
- **Memory and concurrency.** Full collections require more memory. Catalog indexes stay in memory; downloads default to at most four concurrent tasks, font subsetting to two, and books render sequentially.
- **Caches and errors.** Resources are isolated by source configuration and actual URL and written atomically; font subsets are reusable. Old caches are not automatically migrated. Temporary remote failures are tried at most three times per source; 404s may use the fallback source, while network failures are reported distinctly from missing stories.

## Configuration

| Setting | Default | Description |
| --- | --- | --- |
| `TERRA_CACHE_DIR` | `~/.cache/terra-packager` | Root for resources, font subsets, and downloaded Typst |
| `--cache-dir DIR` | Resource cache under the above root | Overrides resources only; fonts/Typst still use the environment setting |
| `TERRA_TYPST_BIN` | Automatic lookup | Explicit local executable; an invalid setting fails directly |
| `TERRA_NOTO_FONT_DIR` | System font lookup | Noto font directory; EPUB defaults to Linux system Noto TTC files |
| `--no-cache` | Off | Bypass persistent resource reads; reuse fetched data within the command and still write caches |
| `--jobs N` | `4` | Concurrent remote downloads, 1–8 |
| `--timings` | Off | Timing and request/cache counts; distinguishes wall time from accumulated task time |
| `--nickname NAME` | Language-specific name | Replace `{@nickname}` placeholders, without replacing ordinary prose globally |

Typst is not bundled. Lookup uses explicit configuration, system PATH, and user cache, then downloads 0.15.1 when a PDF or EPUB build needs it. Fonts may be `NotoSerifCJK-{Regular,Bold}.ttc`, `NotoSerifCJKsc/tc/jp/kr-{Regular,Bold}.otf/.ttf`, or `NotoSerifSC/TC/JP/KR-{Regular,Bold}.otf/.ttf`. PDF/cover lookup uses family names: renaming a file does not change its family. The English template also configures `Noto Serif CJK SC` as its fallback font.

On Ubuntu/Debian, use `sudo apt install fonts-noto-cjk`. Windows example:

```powershell
$env:TERRA_NOTO_FONT_DIR = "C:\fonts\noto"
$env:TERRA_TYPST_BIN = "C:\tools\typst.exe"
terra-packager doctor -l zh -f pdf,epub,txt
```

## Troubleshooting

- **`terra-packager` not found:** activate the environment used for installation, or run `python -m scripts --help` from the source directory.
- **No targets specified:** default separate mode needs a selector. Use `-v main_0`, `--category`, `--content-types`, `--all`, or switch to `--output-mode combined`.
- **Noto font missing / Typst download failed:** run `doctor` and check regular/bold files and font family names. Set `TERRA_TYPST_BIN` when automatic download is unavailable. TXT works independently.
- **Local content missing:** check language directories and source tables, narrow `--content-types`, or explicitly use `--skip-missing` for an incomplete selection.
- **Download failures/timeouts:** check GitHub Raw access, source URLs, and cache permissions, or use local data. `--skip-missing` does not bypass network failures.
- **A bilingual scene appears in two parts:** its source structures cannot be aligned reliably; both complete versions are preserved and marked.
- **Full builds take a long time:** use local data, select less content or TXT, and use `--timings` to separate download, typesetting, and font-subsetting costs.

## Development and Packaging

```sh
python -m pip install ".[dev]" setuptools wheel
python -m build
python -m scripts.benchmark --output tmp/benchmark.json
```

The Windows/Linux workflow builds the package and checks the installed CLI on Python 3.10/3.12. It does not run a test suite or download game data. The synthetic benchmark measures catalog lookup and font-cache reuse; it is not a full-upstream benchmark.

`.venv/`, `build/`, `dist/`, `*.egg-info/`, and `tmp/` are local environment or build artifacts excluded from version control. Package manifests also exclude tests, bundled executables, virtual environments, and temporary output.

## License

The project repository is licensed under the **Apache License, Version 2.0**. See [LICENSE](LICENSE) for the full text and [NOTICE](NOTICE) for third-party attribution. Bundled fonts use the SIL Open Font License; their license texts are in `scripts/assets/licenses/`.

Thanks to ArknightsAssets, Kengxxiao, Typst, and fonttools. Arknights stories, characters, and game content belong to their respective rights holders; code and font licenses do not grant rights to game content.
