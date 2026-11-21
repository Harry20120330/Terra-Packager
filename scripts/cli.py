"""Pure local CLI (`terra-packager list | info | build`) for external Arknights Gamedata repos."""

from __future__ import annotations
import argparse
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .build_diagnostics import BuildDiagnostics
from .dag_linearizer import LinearSection
from .i18n import LANGUAGES
from .packager import create_zip_bundle, normalize_formats, package_sections, package_volume, sanitize_filename
from .repo_provider import ExternalRepoProvider
from .content_collector import COLLECTION_TITLES, CONTENT_LABELS, CONTENT_TYPES, collect_type_sections
from .runtime import Measurements, CURRENT_MEASUREMENTS
from .doctor import check_environment

CATEGORY_ARG_MAP = {
    "mainline": "MAINLINE",
    "activity": "ACTIVITY",
    "sidestory": "ACTIVITY",
    "ministory": "MINI_ACTIVITY",
    "operator": "NONE",
    "record": "NONE",
}

MODE_ALIASES = {"single": "combined", "category": "by-type", "separate": "separate"}
REFERENCE_CATEGORIES = {"archive": "operator-profile", "module": "operator-module"}

STORY_CONTENT_TYPES = {
    "mainline": "MAINLINE",
    "sidestory": "ACTIVITY",
    "ministory": "MINI_ACTIVITY",
    "operator-record": "NONE",
}


def _add_repo_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--repo-dir",
        default=None,
        metavar="DIR",
        help="Local path to a cloned ArknightsGamedata or ArknightsGameData repository (offline)",
    )
    p.add_argument(
        "--yostar-dir",
        default=None,
        metavar="DIR",
        help="Optional YoStar repository path for split Kengxxiao clones",
    )
    p.add_argument(
        "--source",
        default="arknights-assets",
        choices=["arknights-assets", "kengxxiao"],
        help="Remote repository preset when --repo-dir is omitted (default: arknights-assets)",
    )
    p.add_argument(
        "--repo-url",
        default=None,
        metavar="URL",
        help="Custom remote raw base URL",
    )
    p.add_argument(
        "--cache-dir",
        default=None,
        metavar="DIR",
        help="Directory for cached story tables and script files",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
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
            kw in v["volumeNumber"].lower()
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
            f"  {v['volumeNumber']} | {v['groupId']:18s} | {v['categoryTitle']:8s} | "
            f"{v['sceneCount']:2d} scenes | {title}"
        )


def cmd_info(args: argparse.Namespace) -> None:
    provider = _make_provider(args)
    vol = provider.resolve_volume(args.volume, active_langs=list(LANGUAGES), use_cache=not args.no_cache)
    print(f"Volume   : {vol['volumeNumber']} ({vol['groupId']})")
    print(f"Category : {vol['categoryTitle']} ({vol['entryType']})")
    print("Titles   :")
    for lang in LANGUAGES:
        print(f"  - {lang}: {vol['titles'].get(lang, '')}")
    print(f"Scenes ({vol['sceneCount']}):")
    for idx, sc in enumerate(vol["scenesMeta"], start=1):
        tag = f"[{sc['tag']}] " if sc.get("tag") else ""
        t = sc.get(f"title_{args.lang}") or sc["title_zh"]
        print(f"  {idx:02d}. {tag}{t}  ({sc['storyTxt']}.txt)")


def _resolve_build_targets(
    provider: ExternalRepoProvider,
    args: argparse.Namespace,
    active_langs: List[str],
) -> List[str]:
    targets: List[str] = []

    if args.volume:
        targets.extend(x.strip() for x in args.volume.split(",") if x.strip())

    if args.range or args.category or args.all:
        vols = provider.list_volumes(active_langs=active_langs, use_cache=not args.no_cache)
        range_bounds: Optional[tuple[int, int]] = None
        if args.range:
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", args.range.strip())
            if not m:
                raise SystemExit(f"Invalid --range format {args.range!r}; expected e.g. '001-018'")
            range_bounds = (int(m.group(1)), int(m.group(2)))
            if range_bounds[0] < 1 or range_bounds[0] > range_bounds[1]:
                raise ValueError("--range must be an ascending, positive volume range (e.g. '001-018').")

        target_type = CATEGORY_ARG_MAP.get(args.category.lower()) if args.category else None

        for v in vols:
            vnum = int(v["volumeNumber"])
            if range_bounds and not (range_bounds[0] <= vnum <= range_bounds[1]):
                continue
            if target_type and v["entryType"] != target_type:
                continue
            if not (args.all or range_bounds or target_type):
                continue
            targets.append(v["groupId"])

    # Deduplicate preserving order
    deduped = list(dict.fromkeys(targets))
    if not deduped:
        raise SystemExit("No target volumes specified. Pass --volume, --range, --category, or --all.")
    return deduped


def _validate_build_args(args: argparse.Namespace) -> List[str]:
    """Reject invalid requests before reading sources or starting a long build."""
    formats = normalize_formats(args.formats.split(","))
    has_story_selector = bool(args.volume or args.range or args.category)
    if args.all and has_story_selector:
        raise ValueError("--all cannot be combined with --volume, --range, or --category.")
    if args.range:
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", args.range.strip())
        if not match or int(match[1]) < 1 or int(match[1]) > int(match[2]):
            raise ValueError("--range must be an ascending, positive volume range (e.g. '001-018').")
    if args.volume is not None and not any(part.strip() for part in args.volume.split(",")):
        raise ValueError("--volume requires at least one volume number, groupId, or title.")
    if has_story_selector and args.content_types and not any(
        kind in STORY_CONTENT_TYPES for kind in args.content_types
    ):
        raise ValueError("--volume/--range/--category require a story content type in --content-types.")
    if args.output_mode == "separate" and not (has_story_selector or args.all or args.content_types):
        raise ValueError("No targets specified. Pass --volume, --range, --category, --content-types, or --all.")
    if args.zip:
        archive = Path(args.zip)
        if (
            archive.is_absolute() or archive.name != args.zip
            or sanitize_filename(args.zip) != args.zip or archive.suffix.lower() != ".zip"
        ):
            raise ValueError("--zip must be a .zip filename inside --out, e.g. 'library.zip'.")
    return formats


def _normalize_build_options(args: argparse.Namespace) -> None:
    """Accept the reference project's CLI spelling without changing selectors."""
    args.output_mode = args.output_mode or MODE_ALIASES.get(getattr(args, "mode", None), "separate")
    if args.category not in REFERENCE_CATEGORIES:
        return
    if args.all or args.volume or args.range:
        raise ValueError("--category archive/module cannot be combined with --all, --volume, or --range.")
    content_type = REFERENCE_CATEGORIES[args.category]
    if args.content_types and content_type not in args.content_types:
        raise ValueError("--category and --content-types select different content types.")
    args.content_types = [content_type]
    args.category = None


def _select_build_content(
    provider: ExternalRepoProvider,
    args: argparse.Namespace,
    active_langs: List[str],
) -> Tuple[List[str], Optional[List[Dict[str, Any]]]]:
    has_story_selector = bool(args.volume or args.range or args.category)
    wanted = set(args.content_types or (STORY_CONTENT_TYPES if has_story_selector else CONTENT_TYPES))
    # A consistent category order keeps all three output modes easy to compare.
    selected_types = [kind for kind in CONTENT_TYPES if kind in wanted]
    volumes: Optional[List[Dict[str, Any]]] = None
    if has_story_selector:
        targets = _resolve_build_targets(provider, args, active_langs)
        allowed_entries = {STORY_CONTENT_TYPES[kind] for kind in selected_types if kind in STORY_CONTENT_TYPES}
        resolved: Dict[str, Dict[str, Any]] = {}
        for target in targets:
            volume = provider.resolve_volume(target, active_langs=active_langs, use_cache=not args.no_cache)
            if volume["entryType"] in allowed_entries:
                resolved.setdefault(volume["groupId"], volume)
        volumes = list(resolved.values())
        if not volumes:
            raise ValueError("No story volumes match the selected volumes and content types.")
        present = {volume["entryType"] for volume in volumes}
        selected_types = [
            kind for kind in selected_types
            if kind not in STORY_CONTENT_TYPES or STORY_CONTENT_TYPES[kind] in present
        ]
    return selected_types, volumes


def _edition_stem(title: str, primary_lang: str, secondary_lang: Optional[str]) -> str:
    stem = sanitize_filename(title)
    if secondary_lang:
        return f"{stem}-{primary_lang}-{secondary_lang}"
    return f"{stem}-{primary_lang}" if primary_lang != "zh" else stem


def cmd_build(args: argparse.Namespace) -> None:
    metrics = Measurements() if args.timings else None
    token = CURRENT_MEASUREMENTS.set(metrics)
    try:
        _cmd_build(args)
    finally:
        CURRENT_MEASUREMENTS.reset(token)
        if metrics:
            print(metrics.summary())


def cmd_doctor(args: argparse.Namespace) -> None:
    formats = normalize_formats(args.formats.split(","))
    langs = list(dict.fromkeys([args.lang] + ([args.secondary_lang] if args.secondary_lang else [])))
    checks = check_environment(_make_provider(args), langs, formats, args.out)
    for label, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not all(ok for _, ok, _ in checks):
        raise SystemExit(1)


def _cmd_build(args: argparse.Namespace) -> None:
    _normalize_build_options(args)
    formats = _validate_build_args(args)
    if args.secondary_lang == args.lang:
        args.secondary_lang = None
    out_dir = Path(args.out).resolve()
    active_langs = [args.lang] + ([args.secondary_lang] if args.secondary_lang else [])
    provider = _make_provider(args)
    selected_types, selected_volumes = _select_build_content(provider, args, active_langs)

    def log_progress(msg: str, pct: int) -> None:
        print(f"[{pct:3d}%] {msg}", flush=True)

    diagnostics = BuildDiagnostics(on_progress=log_progress, skip_missing=args.skip_missing)

    def render(titles: Dict[str, str], sections: List[LinearSection], stem: str) -> List[Dict[str, Any]]:
        return package_sections(
            volume_titles=titles,
            sections=sections,
            output_stem=_edition_stem(stem, args.lang, args.secondary_lang),
            formats=formats,
            output_dir=out_dir,
            primary_lang=args.lang,
            secondary_lang=args.secondary_lang,
            on_progress=log_progress,
        )

    all_built: List[Dict[str, Any]] = []
    combined_sections: List[LinearSection] = []
    included_types: List[str] = []
    if args.output_mode == "separate" and any(kind in STORY_CONTENT_TYPES for kind in selected_types):
        volumes = selected_volumes if selected_volumes is not None else provider.list_volumes(
            active_langs=active_langs, use_cache=not args.no_cache,
        )
        allowed_entries = {STORY_CONTENT_TYPES[kind] for kind in selected_types if kind in STORY_CONTENT_TYPES}
        volumes = [volume for volume in volumes if volume["entryType"] in allowed_entries]
        present = {volume["entryType"] for volume in volumes}
        missing_types = [
            kind for kind in selected_types
            if kind in STORY_CONTENT_TYPES and STORY_CONTENT_TYPES[kind] not in present
        ]
        for content_type in missing_types:
            diagnostics.empty_category(content_type, CONTENT_LABELS[content_type].get(args.lang, content_type))
        for index, volume in enumerate(volumes, start=1):
            print(f"\n[Vol {index}/{len(volumes)}] {volume['titles'].get(args.lang) or volume['titles']['zh']}", flush=True)
            all_built.extend(package_volume(
                provider=provider,
                volume_identifier=volume["groupId"],
                formats=formats,
                output_dir=out_dir,
                primary_lang=args.lang,
                secondary_lang=args.secondary_lang,
                nickname=args.nickname,
                use_cache=not args.no_cache,
                on_progress=log_progress,
                diagnostics=diagnostics,
                volume=volume,
            ))

    for content_type in selected_types:
        if args.output_mode == "separate" and content_type in STORY_CONTENT_TYPES:
            continue
        label = CONTENT_LABELS[content_type].get(args.lang, content_type)
        print(f"\n[{label}] Collecting content...", flush=True)
        titles, sections = collect_type_sections(
            provider=provider,
            content_type=content_type,
            active_langs=active_langs,
            use_cache=not args.no_cache,
            custom_nickname=args.nickname,
            volumes=selected_volumes,
            on_progress=log_progress,
            diagnostics=diagnostics,
        )
        if not any(section.blocks for section in sections):
            diagnostics.empty_category(content_type, label)
            continue
        included_types.append(content_type)
        if args.output_mode == "combined":
            combined_sections.append(LinearSection(
                scene_id=f"collection_{content_type}",
                raw_tag="",
                titles=dict(CONTENT_LABELS[content_type]),
                blocks=[],
                heading_level=1,
                is_divider=True,
            ))
            combined_sections.extend(replace(section, heading_level=section.heading_level + 1) for section in sections)
        elif args.output_mode == "by-type":
            all_built.extend(render(titles, sections, titles.get(args.lang) or titles["zh"]))
        else:
            # Each archive/module section is one independently readable entry.
            prefix = "profile" if content_type == "operator-profile" else "module"
            for section in sections:
                if not section.blocks:
                    continue
                title = section.titles.get(args.lang) or section.titles.get("zh") or section.scene_id
                stem = f"{prefix}-{title}-{section.scene_id[-12:]}"
                all_built.extend(render(section.titles, [replace(section, heading_level=1)], stem))

    if args.output_mode == "combined" and combined_sections:
        key = "all" if (
            set(included_types) == set(CONTENT_TYPES) and selected_volumes is None and not diagnostics.has_omissions
        ) else "selected"
        titles = COLLECTION_TITLES[key]
        all_built.extend(render(titles, combined_sections, titles.get(args.lang) or titles["zh"]))

    if diagnostics.summary():
        print(f"\n{diagnostics.summary()}", flush=True)
    if not all_built:
        raise ValueError("No content found for the selected content types; no files generated.")
    if args.zip:
        archive = create_zip_bundle(all_built, out_dir / args.zip)
        print(f"\nBundled ZIP archive: {archive} ({archive.stat().st_size:,} bytes)")
    print(f"\nDone! Generated {len(all_built)} file(s) in {out_dir}:")
    for item in all_built:
        print(f"  - {item['fileName']} ({item['size']:,} bytes | sha256={item['sha256'][:12]}...)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="terra-packager",
        description="Build offline EPUB, PDF, and TXT reading packages from Arknights game data.",
        epilog=(
            "Examples:\n"
            "  python launch.py list --category mainline\n"
            "  python launch.py info main_0 --lang en\n"
            "  python launch.py build -v main_0 -l zh -f epub,txt -o output\n"
            "  python launch.py build --all -l zh -f pdf,epub,txt -o output"
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
        help="List story volumes",
        description="List and search story volumes from a local or remote game data repository.",
        epilog="Example: python launch.py list --category mainline --search Babel",
    )
    _add_repo_args(p_list)
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
        help="Inspect one story volume",
        description="Show multilingual titles and the raw .txt scene list for one volume.",
        epilog="Example: python launch.py info main_0 --lang en",
    )
    _add_repo_args(p_info)
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

    # 3. build
    p_build = sub.add_parser(
        "build",
        help="Build EPUB, PDF, and TXT packages",
        description="Compile selected game data into offline EPUB, PDF, and/or TXT packages.",
        epilog=(
            "Examples:\n"
            "  python launch.py build -v main_0 -l zh -f pdf,epub,txt -o output\n"
            "  python launch.py build --repo-dir data/gamedata --category mainline -l en -f epub -o output\n"
            "  python launch.py build --all --output-mode combined -l zh -f txt -o output"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_repo_args(p_build)
    p_build.add_argument(
        "--volume",
        "-v",
        default=None,
        metavar="VOLUME[,VOLUME...]",
        help="Volume number, groupId, or title; separate multiple values with commas",
    )
    p_build.add_argument(
        "--range",
        default=None,
        metavar="START-END",
        help="Build an inclusive volume number range (e.g. '001-018')",
    )
    p_build.add_argument(
        "--category",
        default=None,
        choices=["mainline", "sidestory", "ministory", "operator", "record", "archive", "module"],
        help="Select a category: mainline, sidestory, ministory, operator, record, archive, or module",
    )
    p_build.add_argument(
        "--all",
        action="store_true",
        help="Build all six content types, or the subset given by --content-types",
    )
    mode_group = p_build.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--output-mode",
        choices=["separate", "by-type", "combined"],
        default=None,
        help="Output separately, by content type, or as one combined publication (default: separate)",
    )
    mode_group.add_argument(
        "--mode",
        choices=list(MODE_ALIASES),
        default=None,
        help="Compatibility aliases: single=combined, category=by-type, separate=separate",
    )
    p_build.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip missing scripts and empty content types, with warnings and a summary",
    )
    p_build.add_argument(
        "--content-types",
        nargs="+",
        choices=CONTENT_TYPES,
        default=None,
        metavar="TYPE",
        help="Content types: " + ", ".join(CONTENT_TYPES) + " (aggregate modes default to all six)",
    )
    p_build.add_argument(
        "--formats",
        "-f",
        default="pdf,epub,txt",
        metavar="FORMAT[,FORMAT...]",
        help="Comma-separated output formats: pdf, epub, txt (default: all three)",
    )
    p_build.add_argument(
        "--lang",
        "-l",
        default="zh",
        choices=LANGUAGES,
        help="Primary language: zh, tw, en, ja, ko (default: zh)",
    )
    p_build.add_argument(
        "--secondary-lang",
        "-s",
        default=None,
        choices=LANGUAGES,
        help="Optional secondary language for a bilingual parallel edition",
    )
    p_build.add_argument(
        "--nickname",
        default=None,
        metavar="NAME",
        help="Override the Doctor's displayed nickname",
    )
    p_build.add_argument(
        "--out",
        "-o",
        default="output",
        metavar="DIR",
        help="Output directory (default: ./output)",
    )
    p_build.add_argument(
        "--zip",
        default=None,
        metavar="FILE.zip",
        help="Optional ZIP filename to create inside --out",
    )
    p_build.set_defaults(func=cmd_build)

    p_build.add_argument("--jobs", type=int, choices=range(1, 9), default=4, metavar="N", help="Concurrent remote downloads (1-8, default: 4)")
    p_build.add_argument("--timings", action="store_true", help="Report stage timings and cache counters")

    p_doctor = sub.add_parser("doctor", help="Check the environment without downloading or creating files")
    _add_repo_args(p_doctor)
    p_doctor.add_argument("--lang", "-l", choices=LANGUAGES, default="zh")
    p_doctor.add_argument("--secondary-lang", "-s", choices=LANGUAGES)
    p_doctor.add_argument("--formats", "-f", default="pdf,epub,txt")
    p_doctor.add_argument("--out", "-o", default="output")
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    try:
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
