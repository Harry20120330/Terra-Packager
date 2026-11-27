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
- **Publication and archives:** Typst A4 PDFs, EPUB 3 with nested navigation and embedded fonts, UTF-8 TXT, and embedded cover images.
- **Build diagnostics:** environment checks, concurrent downloads, catalog indexes, and cached font subsets.

[Repository](https://github.com/Harry20120330/Terra-Packager) · [Issues](https://github.com/Harry20120330/Terra-Packager/issues)

## Project Structure

- `launch.py`: source entry point for the same CLI as `terra-packager`.
- `LICENSE` / `NOTICE`: the project license and third-party attribution notices.
- `scripts/cli.py`: the `list`, `info`, `build`, and `doctor` commands.
- `scripts/data_source.py`: shared local-data detection, explicit Git clones, and download retries.
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

`build` always includes all six content types. Choose the format, language, and output grouping; finished files go into `./output`:

```sh
# One complete collection
terra-packager build -f epub -l zh --output-mode combined

# One book per content type
terra-packager build -f pdf,epub,txt -l zh --output-mode by-type

# Separate volumes and entries (default mode)
terra-packager build -f txt -l zh --output-mode separate

# Optional bilingual edition
terra-packager build -f epub -l zh -s en --output-mode combined
```

From the source checkout, use `python launch.py` or `python -m scripts` instead of `terra-packager`. Defaults are formats `pdf,epub,txt`, language `zh`, and grouping `separate`. No selection flags are required.

| `--output-mode` | Organization | All six types and three formats |
| --- | --- | --- |
| `combined` | One complete collection | 3 files |
| `by-type` | One book per type | 18 files |
| `separate` (default) | Stories/records per volume, profiles per operator, modules per entry | 3 files per unit |

Separate books live in `output/mainline/`, `sidestory/`, `ministory/`, `operator-profile/`, `operator-record/`, and `operator-module/`, preventing collisions between categories. Main story numbers start at `000`; side stories and vignettes each start at `001`. Records have no volume number and use “Operator name · Record title”; a stable suffix distinguishes identical record filenames.

This version removes the old build selectors, ranges, categories, content filters, `--all`, mode aliases, custom output paths, ZIP, download/source options, and other advanced build flags. Replace older commands with the three settings above.

### Data and Inspection

Builds automatically detect `./data/ArknightsGamedata`. Without local data, required files are fetched from GitHub Raw and cached. To prepare local data:

```sh
git clone --depth 1 https://github.com/ArknightsAssets/ArknightsGamedata.git data/ArknightsGamedata
terra-packager build -f txt --output-mode combined
```

Supported local layouts include `{cn,tw,en,jp,kr}/gamedata`, `{zh_CN,zh_TW,en_US,ja_JP,ko_KR}/gamedata`, bare `gamedata`, and directories containing `excel`. Full builds require story catalogs/scripts, character, handbook, and module tables.

`list`, `info`, and `doctor` remain available. Put their data/source options after the subcommand:

```sh
terra-packager list --category mainline
terra-packager list --category record --search Kroos
terra-packager info main_0 --lang en
terra-packager list --repo-dir data/ArknightsGamedata --limit 0
terra-packager list --download --category mainline
terra-packager doctor -l zh -f epub
```

Use unique `groupId` values with `info`. A numeric identifier shared by categories reports candidate IDs rather than silently selecting the first match. Records can be inspected with IDs such as `story_kroos_set_1`.

Inspection commands retain `--source arknights-assets/kengxxiao`, `--repo-url`, `--repo-dir`, `--yostar-dir`, `--cache-dir`, `--no-cache`, and explicit `--download`. Downloads shallow-clone missing local data; help and `doctor` never download. Clones use HTTP/1.1 and up to three retries without modifying global Git settings or discarding existing directories.

### EPUB and Kindle

EPUB reading order is **image-only cover → standalone contents chapter → main story → remaining content**. The cover has no navigation buttons. EPUB 3 landmarks and legacy guide references identify the cover, contents, and body separately.

The combined EPUB starts its contents page with a quick index linking directly to each populated category, followed by the detailed table of contents.

The AZW3 conversion baseline is boko 0.6.0:

```sh
boko convert output/book.epub book.azw3
```

Boko exports the body landmark as `text`, while its default Beginning entry may still point to the start of the book. Use the independent contents chapter to select Main Story. Page/location values come from the converter and reader; validation checks their order against actual content, without inventing EPUB page numbers from PDF pagination.

## Notes

- **Offline requirements.** Detected local data never fetches missing files from the network. Fully offline PDF/EPUB builds also need Typst and fonts prepared beforehand; wheels contain no platform-specific Typst executable.
- **Bilingual alignment.** Matching branch intervals pair prose in source order and retain extra paragraphs. Incompatible structures output complete primary and secondary scenes separately with a notice; sentence-level semantic alignment is not guaranteed.
- **Branch syntax.** All-option predicates before individual branches retain the choice scope. Nested decisions can join through combined child values, and multiple options can share one value; all labels are kept and shared prose is printed once.
- **Video-only scenes.** AVG scripts containing video playback and no printable text are skipped automatically with a notice and summary count. Missing files, empty files, and scripts whose prose fails to survive compilation still fail normally; an entirely empty publication is never generated.
- **Inconsistent branch data.** If an upstream script contains predicate references that cannot be resolved, or more choice labels than branch values, a warning identifies the script and language. Its complete prose and choice labels are retained in source order, without inferred branch connections, and counted in the build summary. Unfinished multiline dialogue is emitted before the next normal dialogue line.
- **Missing translations/content.** Bilingual stories retain available languages; profiles/modules may show original prose with a missing-translation marker. Missing or empty content, corrupt JSON, empty decision values, and network failures are reported as errors. An entirely empty result fails.
- **Finished files.** All requested formats for a book are built in a temporary directory before replacing final files. Renderer failures preserve existing outputs and earlier completed books.
- **Memory and concurrency.** Full collections require more memory. Catalog indexes stay in memory; downloads default to at most four concurrent tasks, font subsetting to two, and books render sequentially.
- **Caches and errors.** Resources are isolated by source configuration and actual URL and written atomically; font subsets are reusable. Old caches are not automatically migrated. Temporary remote failures, including interrupted HTTP response bodies, are tried at most three times per source; 404s may use the fallback source, while network failures are reported distinctly from missing stories.

## Configuration

| Setting | Default | Description |
| --- | --- | --- |
| `TERRA_CACHE_DIR` | `~/.cache/terra-packager` | Root for resources, font subsets, and downloaded Typst |
| `--cache-dir DIR` | Inspection commands use the above root | Overrides resources only; fonts/Typst still use the environment setting |
| `TERRA_TYPST_BIN` | Automatic lookup | Explicit local executable; an invalid setting fails directly |
| `TERRA_NOTO_FONT_DIR` | System font lookup | Noto font directory; EPUB defaults to Linux system Noto TTC files |
| `--no-cache` | Off | Bypass persistent resource reads; reuse fetched data within the command and still write caches |

Typst is not bundled. Lookup uses explicit configuration, system PATH, and user cache, then downloads 0.15.1 when a PDF or EPUB build needs it. Automatic downloads support x86-64 and ARM64 on Linux/macOS, and x86-64 on Windows. Other platforms require a compatible executable via `TERRA_TYPST_BIN`. Fonts may be `NotoSerifCJK-{Regular,Bold}.ttc`, `NotoSerifCJKsc/tc/jp/kr-{Regular,Bold}.otf/.ttf`, or `NotoSerifSC/TC/JP/KR-{Regular,Bold}.otf/.ttf`. PDF/cover lookup uses family names: renaming a file does not change its family. The English template also configures `Noto Serif CJK SC` as its fallback font.

On Ubuntu/Debian, use `sudo apt install fonts-noto-cjk`. Windows example:

```powershell
$env:TERRA_NOTO_FONT_DIR = "C:\fonts\noto"
$env:TERRA_TYPST_BIN = "C:\tools\typst.exe"
terra-packager doctor -l zh -f pdf,epub,txt
```

## Troubleshooting

- **`terra-packager` not found:** activate the environment used for installation, or run `python -m scripts --help` from the source directory.
- **Old build flags unrecognized:** `build` accepts only formats, languages, and grouping. To download local data first, run `terra-packager list --download`, then `build`. Update an older installed CLI with `python -m pip install --upgrade .` in its active environment.
- **`Unscoped predicate references` / `Unknown predicate references` on an older install:** update the whole source checkout, including `launch.py` and `scripts/`, then run `python -m pip install --upgrade .` in the active environment. Version 1.0.0 retains excess choice labels and fixes interrupted multiline dialogue ordering, alongside shared gates, combined child joins, and repeated option values.
- **A full local build stops at `act13mini`:** some ArknightsAssets snapshots have the catalog for this event but lack its six Chinese story files. Prepare those files from the Kengxxiao source, or use a complete local checkout. Local builds never fill missing data from the network automatically.
- **Noto font missing / Typst download failed:** run `doctor` and check regular/bold files and font family names. Set `TERRA_TYPST_BIN` when automatic download is unavailable. TXT works independently.
- **Local content missing:** check language directories and source tables/scripts for all six content types, then restore missing files.
- **Download failures/timeouts:** check GitHub Raw access, source URLs, and cache permissions, or use local data.
- **Git clone TLS termination (`GnuTLS recv error (-110)`):** HTTPS cloning now retries without changing global Git settings. If all attempts fail, check your network/proxy or use `terra-packager list --source arknights-assets` to fetch required files on demand. An older failed clone that left a nonempty destination needs a new `--data-dir` or manual inspection before removal.
- **A bilingual scene appears in two parts:** its source structures cannot be aligned reliably; both complete versions are preserved and marked.
- **Full builds take a long time:** use complete local data; choose `-f txt` when typesetting and embedded fonts are unnecessary.

## Development and Packaging

```sh
python -m pip install ".[dev]" setuptools wheel
python -m build
python -m scripts.benchmark --output tmp/benchmark.json
```

The Windows/Linux workflow builds the package and checks the installed CLI on Python 3.10/3.12 without downloading game data. The synthetic benchmark measures catalog lookup and font-cache reuse; it is not a full-upstream benchmark.

`.venv/`, `build/`, `dist/`, `*.egg-info/`, and `tmp/` are local environment or build artifacts excluded from version control. Package manifests also exclude tests, bundled executables, virtual environments, and temporary output.

## License

The project repository is licensed under the **Apache License, Version 2.0**. See [LICENSE](LICENSE) for the full text and [NOTICE](NOTICE) for third-party attribution. Bundled fonts use the SIL Open Font License; their license texts are in `scripts/assets/licenses/`.

Thanks to ArknightsAssets, Kengxxiao, Typst, and fonttools. Arknights stories, characters, and game content belong to their respective rights holders; code and font licenses do not grant rights to game content.
