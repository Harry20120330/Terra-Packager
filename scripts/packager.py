"""Core packaging orchestrator: External Gamedata Repo -> EPUB / PDF / TXT."""

from __future__ import annotations
import hashlib
import re
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .build_diagnostics import BuildDiagnostics
from .dag_linearizer import LinearSection
from .epub_builder import write_epub
from .i18n import LANGUAGES, get_edition_badge
from .pdf_builder import compile_pdf_and_cover
from .repo_provider import CONTENT_ENTRY_TYPES, ExternalRepoProvider
from .txt_builder import write_txt
from .runtime import measured


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "·", name.strip()).rstrip(". ")
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", cleaned):
        cleaned = "_" + cleaned
    return cleaned or "volume"


def normalize_formats(formats: List[str]) -> List[str]:
    """Validate the whole format request instead of silently dropping typos."""
    normalized = list(dict.fromkeys(fmt.strip().lower() for fmt in formats if fmt.strip()))
    invalid = [fmt for fmt in normalized if fmt not in ("pdf", "epub", "txt")]
    if invalid or not normalized:
        raise ValueError(f"Invalid output formats: {', '.join(invalid) or '(empty)'}. Choose pdf, epub, txt.")
    return normalized


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_volume(
    provider: ExternalRepoProvider,
    volume_identifier: str,
    formats: List[str],
    output_dir: Path,
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
    nickname: Optional[str] = None,
    use_cache: bool = True,
    on_progress: Optional[Callable[[str, int], None]] = None,
    diagnostics: Optional[BuildDiagnostics] = None,
    volume: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    formats = normalize_formats(formats)
    if primary_lang not in LANGUAGES:
        raise ValueError(f"Unsupported primary_lang: {primary_lang}")
    if secondary_lang and secondary_lang not in LANGUAGES:
        raise ValueError(f"Unsupported secondary_lang: {secondary_lang}")
    if secondary_lang == primary_lang:
        secondary_lang = None

    active_langs = [primary_lang] + ([secondary_lang] if secondary_lang else [])
    diagnostics = diagnostics if diagnostics is not None else BuildDiagnostics(on_progress=on_progress)

    def report(msg: str, pct: int) -> None:
        if on_progress:
            on_progress(msg, pct)

    report(f"[1/4] Resolving the volume catalog from {provider.source}...", 8)
    vol = volume if volume is not None else provider.resolve_volume(volume_identifier, active_langs=active_langs, use_cache=use_cache)
    vol_num = vol["volumeNumber"]
    p_vol_title = vol["titles"].get(primary_lang) or vol["titles"]["zh"]
    title_stem = sanitize_filename(p_vol_title)
    numbered_stem = f"{vol_num}-{title_stem}" if vol_num is not None else title_stem
    if secondary_lang:
        base_stem = f"{numbered_stem}-{primary_lang}-{secondary_lang}"
    elif primary_lang == "zh":
        base_stem = numbered_stem
    else:
        base_stem = f"{numbered_stem}-{primary_lang}"
    # Same operator can have multiple records with the same title.
    if vol_num is None:
        base_stem += "-" + hashlib.sha256(vol["groupId"].encode()).hexdigest()[:12]
    content_type = next((kind for kind, entry in CONTENT_ENTRY_TYPES.items() if entry == vol["entryType"]), "story")

    scenes_meta = vol["scenesMeta"]
    total_sc = len(scenes_meta)
    sections: List[LinearSection] = []
    provider.prefetch(((lang, f"story/{meta['storyTxt']}.txt")
                       for meta in scenes_meta for lang in active_langs), use_cache)

    for idx, sc_meta in enumerate(scenes_meta, start=1):
        pct = 10 + int(35 * idx / max(1, total_sc))
        report(
            f"[2/4] Fetching and compiling AVG script ({idx}/{total_sc}): {sc_meta.get('storyTxt')}",
            pct,
        )
        section = diagnostics.compile_scene(
            provider=provider,
            scene_meta=sc_meta,
            active_langs=active_langs,
            use_cache=use_cache,
            custom_nickname=nickname,
        )
        if section is not None:
            sections.append(section)

    if not sections and diagnostics.skip_missing:
        return []

    divider = LinearSection(
        scene_id="volume_" + hashlib.sha256(vol["groupId"].encode()).hexdigest()[:20],
        raw_tag=vol_num or "",
        titles=dict(vol["titles"]),
        blocks=[],
        is_divider=True,
    )
    sections = [divider, *(replace(section, heading_level=2) for section in sections)]

    return package_sections(
        volume_titles=vol["titles"],
        sections=sections,
        output_stem=base_stem,
        formats=formats,
        output_dir=Path(output_dir) / content_type,
        primary_lang=primary_lang,
        secondary_lang=secondary_lang,
        use_cache=use_cache,
        on_progress=on_progress,
        volume_number=vol_num,
        group_id=vol["groupId"],
    )


def package_sections(
    volume_titles: Dict[str, str],
    sections: List[LinearSection],
    output_stem: str,
    formats: List[str],
    output_dir: Path,
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
    use_cache: bool = True,
    on_progress: Optional[Callable[[str, int], None]] = None,
    volume_number: Optional[str] = None,
    group_id: Optional[str] = None,
    epub_sections: Optional[List[LinearSection]] = None,
) -> List[Dict[str, Any]]:
    """Render a prepared collection of sections to the requested publication formats."""
    if primary_lang not in LANGUAGES:
        raise ValueError(f"Unsupported primary_lang: {primary_lang}")
    if secondary_lang and secondary_lang not in LANGUAGES:
        raise ValueError(f"Unsupported secondary_lang: {secondary_lang}")
    if secondary_lang == primary_lang:
        secondary_lang = None

    def report(msg: str, pct: int) -> None:
        if on_progress:
            on_progress(msg, pct)

    needed_formats = normalize_formats(formats)
    if not any(section.blocks for section in sections):
        raise ValueError("Cannot publish an empty collection.")
    if not output_stem or sanitize_filename(output_stem) != output_stem:
        raise ValueError("output_stem must be a valid filename without path separators.")
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []

    # Stage each publication so a renderer failure leaves existing finished books intact.
    with tempfile.TemporaryDirectory(prefix=".terra_", dir=output_dir) as staging_dir:
        staging = Path(staging_dir)
        cover_bytes = b""
        if "pdf" in needed_formats or "epub" in needed_formats:
            report("[3/4] Rendering the A4 PDF and cover with Typst...", 60)
            cover_path = staging / "cover.png" if "epub" in needed_formats else None
            compile_pdf_and_cover(
                pdf_output_path=staging / "book.pdf" if "pdf" in needed_formats else None,
                cover_png_path=cover_path,
                volume_titles=volume_titles,
                sections=sections,
                primary_lang=primary_lang,
                secondary_lang=secondary_lang,
            )
            if cover_path is not None:
                cover_bytes = cover_path.read_bytes()

        if "epub" in needed_formats:
            report("[4/4] Subsetting fonts and packaging EPUB 3.0...", 82)
            write_epub(
                output_path=staging / "book.epub",
                volume_titles=volume_titles,
                sections=epub_sections if epub_sections is not None else sections,
                cover_png_bytes=cover_bytes,
                primary_lang=primary_lang,
                secondary_lang=secondary_lang,
            )
        if "txt" in needed_formats:
            report("[4/4] Exporting UTF-8 plain text (.txt)...", 94)
            write_txt(
                output_path=staging / "book.txt",
                volume_titles=volume_titles,
                sections=sections,
                primary_lang=primary_lang,
                secondary_lang=secondary_lang,
            )

        for fmt in needed_formats:
            staged = staging / f"book.{fmt}"
            if not staged.is_file() or staged.stat().st_size == 0:
                raise ValueError(f"Renderer did not produce a nonempty {fmt.upper()} file.")
        for fmt in needed_formats:
            output = output_dir / f"{output_stem}.{fmt}"
            (staging / f"book.{fmt}").replace(output)
            results.append({
                "format": fmt,
                "fileName": output.name,
                "path": str(output),
                "size": output.stat().st_size,
                "sha256": _file_sha256(output),
                "edition": get_edition_badge(primary_lang, secondary_lang),
                "volumeNumber": volume_number,
                "groupId": group_id,
                "volumeTitle": volume_titles.get(primary_lang) or volume_titles.get("zh") or output_stem,
            })

    report(f"Package complete: {output_stem} ({', '.join(needed_formats).upper()})", 100)
    order_map = {f: i for i, f in enumerate(needed_formats)}
    results.sort(key=lambda r: order_map.get(r["format"], 99))
    return results


def create_zip_bundle(items: List[Dict[str, Any]], zip_path: Path) -> Path:
    zip_path = Path(zip_path).resolve()
    seen: set[str] = set()
    for item in items:
        source = Path(item["path"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Cannot bundle missing output: {source}")
        if source == zip_path:
            raise ValueError("ZIP output cannot overwrite one of its inputs.")
        if item["fileName"] in seen:
            raise ValueError(f"Duplicate filename in ZIP bundle: {item['fileName']}")
        seen.add(item["fileName"])
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".terra_zip_", dir=zip_path.parent) as tmpdir:
        staged = Path(tmpdir) / "bundle.zip"
        with measured("archive"):
            with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for item in items:
                    zf.write(item["path"], item["fileName"])
        staged.replace(zip_path)
    return zip_path
