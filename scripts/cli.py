"""Shared CLI for terra-packager, launch.py, and python -m scripts."""

from __future__ import annotations
import argparse
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from .build_diagnostics import BuildDiagnostics
from .data_source import add_download_args, prepare_data_source
from .dag_linearizer import LinearSection
from .i18n import LANGUAGES
from .packager import normalize_formats, package_sections, package_volume, sanitize_filename
from .repo_provider import ExternalRepoProvider
from .content_collector import COLLECTION_TITLES, CONTENT_LABELS, CONTENT_TYPES, collect_type_sections, group_operator_entries
from .runtime import CURRENT_MEASUREMENTS
from .doctor import check_environment

CATEGORY_ARG_MAP = {
    "mainline": "MAINLINE",
    "activity": "ACTIVITY",
    "sidestory": "ACTIVITY",
    "ministory": "MINI_ACTIVITY",
    "operator": "NONE",
    "record": "NONE",
}

STORY_CONTENT_TYPES = {
    "mainline": "MAINLINE",
    "sidestory": "ACTIVITY",
    "ministory": "MINI_ACTIVITY",
    "operator-record": "NONE",
}


def _add_repo_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--repo-dir",
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="Local path to a cloned ArknightsGamedata or ArknightsGameData repository (offline)",
    )
    p.add_argument(
        "--yostar-dir",
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="Optional YoStar repository path for split Kengxxiao clones",
    )
    p.add_argument(
        "--source",
        default=argparse.SUPPRESS,
        choices=["arknights-assets", "kengxxiao"],
        help="Remote repository preset when --repo-dir is omitted (default: arknights-assets)",
    )
    p.add_argument(
        "--repo-url",
        default=argparse.SUPPRESS,
        metavar="URL",
        help="Custom remote raw base URL",
    )
    p.add_argument(
        "--cache-dir",
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="Directory for cached story tables and script files",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Bypass the local cache and re-read source files",
    )


def _make_provider(args: argparse.Namespace) -> ExternalRepoProvider:
    return ExternalRepoProvider(
        source=args.source,
        repo_dir=Path(args.repo_dir) if args.repo_dir else None,
        yostar_dir=Path(args.yostar_dir) if args.yostar_dir else None,
        repo_url=args.repo_url,
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        jobs=getattr(args, "jobs", 4),
        measurements=CURRENT_MEASUREMENTS.get(),
    )


def cmd_list(args: argparse.Namespace) -> None:
    provider = _make_provider(args)
    vols = provider.list_volumes(active_langs=[args.lang], use_cache=not args.no_cache)

    target_entry_type = CATEGORY_ARG_MAP.get(args.category.lower()) if args.category else None
    kw = (args.search or "").strip().lower()

    matched = []
    for v in vols:
        if target_entry_type and v["entryType"] != target_entry_type:
            continue
        if kw and not (
            kw in (v["volumeNumber"] or "").lower()
            or kw in v["groupId"].lower()
            or any(kw in t.lower() for t in v["titles"].values())
        ):
            continue
        matched.append(v)

    limit = args.limit if args.limit > 0 else len(matched)
    print(f"Found {len(matched)} volumes (showing {min(limit, len(matched))}):")
    for v in matched[:limit]:
        title = v["titles"].get(args.lang) or v["titles"]["zh"]
        print(
            f"  {v['volumeNumber'] or '-':3s} | {v['groupId']:18s} | {v['categoryTitle']:8s} | "
            f"{v['sceneCount']:2d} scenes | {title}"
        )


def cmd_info(args: argparse.Namespace) -> None:
    provider = _make_provider(args)
    vol = provider.resolve_volume(args.volume, active_langs=list(LANGUAGES), use_cache=not args.no_cache)
    print(f"Volume   : {vol['volumeNumber'] or '-'} ({vol['groupId']})")
    print(f"Category : {vol['categoryTitle']} ({vol['entryType']})")
    print("Titles   :")
    for lang in LANGUAGES:
        print(f"  - {lang}: {vol['titles'].get(lang, '')}")
    print(f"Scenes ({vol['sceneCount']}):")
    for idx, sc in enumerate(vol["scenesMeta"], start=1):
        tag = f"[{sc['tag']}] " if sc.get("tag") else ""
        t = sc.get(f"title_{args.lang}") or sc["title_zh"]
        print(f"  {idx:02d}. {tag}{t}  ({sc['storyTxt']}.txt)")


def _edition_stem(title: str, primary_lang: str, secondary_lang: Optional[str]) -> str:
    stem = sanitize_filename(title)
    if secondary_lang:
        return f"{stem}-{primary_lang}-{secondary_lang}"
    return f"{stem}-{primary_lang}" if primary_lang != "zh" else stem


def cmd_build(args: argparse.Namespace) -> None:
    _cmd_build(args)


def cmd_doctor(args: argparse.Namespace) -> None:
    formats = normalize_formats(args.formats.split(","))
    langs = list(dict.fromkeys([args.lang] + ([args.secondary_lang] if args.secondary_lang else [])))
    checks = check_environment(_make_provider(args), langs, formats, args.out)
    for label, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not all(ok for _, ok, _ in checks):
        raise SystemExit(1)


def _cmd_build(args: argparse.Namespace) -> None:
    formats = normalize_formats(args.formats.split(","))
    if args.secondary_lang == args.lang:
        args.secondary_lang = None
    out_dir = (Path.cwd() / "output").resolve()
    active_langs = [args.lang] + ([args.secondary_lang] if args.secondary_lang else [])
    provider = _make_provider(args)

    def log_progress(msg: str, pct: int) -> None:
        print(f"[{pct:3d}%] {msg}", flush=True)

    diagnostics = BuildDiagnostics(on_progress=log_progress)

    def render(titles, sections, stem, directory=out_dir, epub_sections=None):
        return package_sections(
            volume_titles=titles, sections=sections,
            output_stem=_edition_stem(stem, args.lang, args.secondary_lang),
            formats=formats, output_dir=directory, primary_lang=args.lang,
            secondary_lang=args.secondary_lang, on_progress=log_progress, epub_sections=epub_sections,
        )

    all_built: List[Dict[str, Any]] = []
    combined_sections: List[LinearSection] = []
    combined_epub_sections: Optional[List[LinearSection]] = [] if "epub" in formats else None
    if args.output_mode == "separate":
        volumes = provider.list_volumes(active_langs=active_langs)
        present = {volume["entryType"] for volume in volumes}
        for kind, entry in STORY_CONTENT_TYPES.items():
            if entry not in present:
                diagnostics.empty_category(kind, CONTENT_LABELS[kind][args.lang])
        for index, volume in enumerate(volumes, start=1):
            print(f"\n[Vol {index}/{len(volumes)}] {volume['titles'][args.lang]}", flush=True)
            all_built.extend(package_volume(
                provider=provider, volume_identifier=volume["groupId"], volume=volume,
                formats=formats, output_dir=out_dir, primary_lang=args.lang,
                secondary_lang=args.secondary_lang, on_progress=log_progress, diagnostics=diagnostics,
            ))

    for content_type in CONTENT_TYPES:
        if args.output_mode == "separate" and content_type in STORY_CONTENT_TYPES:
            continue
        label = CONTENT_LABELS[content_type][args.lang]
        print(f"\n[{label}] Collecting content...", flush=True)
        titles, sections = collect_type_sections(
            provider=provider, content_type=content_type, active_langs=active_langs,
            on_progress=log_progress, diagnostics=diagnostics,
        )
        if not any(section.blocks for section in sections):
            diagnostics.empty_category(content_type, label)
        if args.output_mode == "combined":
            divider = LinearSection(
                scene_id=f"collection_{content_type}", raw_tag="",
                titles=dict(CONTENT_LABELS[content_type]), blocks=[], heading_level=1, is_divider=True,
            )
            category_sections = [divider, *(replace(section, heading_level=section.heading_level + 1)
                                            for section in sections)]
            combined_sections.extend(category_sections)
            if combined_epub_sections is not None:
                if content_type in {"operator-record", "operator-module"}:
                    grouped = group_operator_entries(content_type, sections)
                    combined_epub_sections.append(divider)
                    combined_epub_sections.extend(replace(section, heading_level=section.heading_level + 1)
                                                  for section in grouped)
                else:
                    combined_epub_sections.extend(category_sections)
        elif args.output_mode == "by-type":
            all_built.extend(render(titles, sections, titles[args.lang]))
        else:
            prefix = "profile" if content_type == "operator-profile" else "module"
            for section in sections:
                if not section.blocks:
                    continue
                title = section.titles.get(args.lang) or section.titles["zh"]
                stem = f"{prefix}-{title}-{section.scene_id[-12:]}"
                all_built.extend(render(section.titles, [replace(section, heading_level=1)], stem,
                                        out_dir / content_type))

    if args.output_mode == "combined":
        titles = COLLECTION_TITLES["all"]
        all_built.extend(render(titles, combined_sections, titles[args.lang], epub_sections=combined_epub_sections))
    if diagnostics.summary():
        print(f"\n{diagnostics.summary()}", flush=True)
    if not all_built:
        raise ValueError("No readable content found; no files generated.")
    print(f"\nDone! Generated {len(all_built)} file(s) in {out_dir}:")
    for item in all_built:
        print(f"  - {Path(item['path']).relative_to(out_dir)} ({item['size']:,} bytes)")


def main(argv: Optional[List[str]] = None) -> None:
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    _add_repo_args(common)
    add_download_args(common)
    parser = argparse.ArgumentParser(
        prog="terra-packager",
        allow_abbrev=False,
        description="Build offline EPUB, PDF, and TXT reading packages from Arknights game data.",
        epilog=(
            "Examples:\n"
            "  python launch.py list --category mainline\n"
            "  python launch.py info main_0 --lang en\n"
            "  python launch.py build -l zh -f epub,txt --output-mode combined\n"
            "  python launch.py build -l zh -f pdf,epub,txt --output-mode separate"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="{list,info,build,doctor}",
    )

    # 1. list
    p_list = sub.add_parser(
        "list",
        parents=[common],
        allow_abbrev=False,
        help="List story volumes",
        description="List and search story volumes from a local or remote game data repository.",
        epilog="Example: python launch.py list --category mainline --search Babel",
    )
    p_list.add_argument(
        "--lang",
        default="zh",
        choices=LANGUAGES,
        help="Language used for displayed titles (default: zh)",
    )
    p_list.add_argument(
        "--category",
        default=None,
        choices=["mainline", "sidestory", "ministory", "operator", "record"],
        help="Filter by category: mainline, sidestory, ministory, operator, or record",
    )
    p_list.add_argument(
        "--search",
        default=None,
        metavar="TEXT",
        help="Filter by volume number, groupId, or title keyword",
    )
    p_list.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Maximum rows to print; use 0 for unlimited (default: 50)",
    )
    p_list.set_defaults(func=cmd_list)

    # 2. info
    p_info = sub.add_parser(
        "info",
        parents=[common],
        allow_abbrev=False,
        help="Inspect one story volume",
        description="Show multilingual titles and the raw .txt scene list for one volume.",
        epilog="Example: python launch.py info main_0 --lang en",
    )
    p_info.add_argument(
        "volume",
        metavar="VOLUME",
        help="Volume number ('001'), groupId ('main_0'), or title",
    )
    p_info.add_argument(
        "--lang",
        default="zh",
        choices=LANGUAGES,
        help="Language used for scene titles (default: zh)",
    )
    p_info.set_defaults(func=cmd_info)

    # Build exposes only publication format, language, and grouping.
    p_build = sub.add_parser(
        "build", allow_abbrev=False,
        help="Build all six content types",
        description="Build all content into ./output; local data is detected automatically.",
        epilog="Example: python launch.py build -f epub -l zh --output-mode combined",
    )
    p_build.add_argument(
        "--formats", "-f", default="pdf,epub,txt", metavar="FORMAT[,FORMAT...]",
        help="Comma-separated pdf, epub, txt (default: all three)",
    )
    p_build.add_argument("--lang", "-l", default="zh", choices=LANGUAGES, help="Primary language (default: zh)")
    p_build.add_argument("--secondary-lang", "-s", default=None, choices=LANGUAGES, help="Optional bilingual language")
    p_build.add_argument(
        "--output-mode", choices=["combined", "by-type", "separate"], default="separate",
        help="combined: one book; by-type: six books; separate: per volume/entry (default)",
    )
    p_build.set_defaults(func=cmd_build)

    p_doctor = sub.add_parser(
        "doctor", parents=[common], allow_abbrev=False,
        help="Check the environment without downloading or creating files",
    )
    p_doctor.add_argument("--lang", "-l", choices=LANGUAGES, default="zh")
    p_doctor.add_argument("--secondary-lang", "-s", choices=LANGUAGES)
    p_doctor.add_argument("--formats", "-f", default="pdf,epub,txt")
    p_doctor.add_argument("--out", "-o", default="output")
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    explicit_source = any(hasattr(args, name) for name in ("repo_dir", "source", "repo_url"))
    defaults = {
        "repo_dir": None, "yostar_dir": None, "source": "arknights-assets", "repo_url": None,
        "cache_dir": None, "no_cache": False, "download": False, "data_dir": None, "repository": None,
    }
    for name, value in defaults.items():
        vars(args).setdefault(name, value)
    try:
        # Validate the format request before reading local or remote data.
        if args.command == "build":
            normalize_formats(args.formats.split(","))
        prepare_data_source(args, explicit_source)
        args.func(args)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        parser.exit(2, f"terra-packager: error: {exc}\n")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        parser.exit(1, f"terra-packager: renderer failed:\n{detail}\n")
    except (RuntimeError, OSError) as exc:
        parser.exit(1, f"terra-packager: error: {exc}\n")


if __name__ == "__main__":
    main()
