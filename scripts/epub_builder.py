"""EPUB 3.0 publication builder with pyftsubset 5-language font subsetting."""

from __future__ import annotations
import hashlib
import html
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from .dag_linearizer import LinearSection
from .i18n import EPUB_LANG_TAGS, NOTO_TTC_INDEX, UI_STRINGS, localize_stage_tag
from .runtime import atomic_write, cache_root, CURRENT_MEASUREMENTS, measured

PUBLISHER_DIR = Path(__file__).resolve().parent
STYLE_TEMPLATE_PATH = PUBLISHER_DIR / "templates" / "epub_style.css"
FONTS_DIR = PUBLISHER_DIR / "assets" / "fonts"
LICENSES_DIR = PUBLISHER_DIR / "assets" / "licenses"
_DEFAULT_FONT_DIR = Path("/usr/share/fonts/opentype/noto")
NOTO_REGULAR_TTC = _DEFAULT_FONT_DIR / "NotoSerifCJK-Regular.ttc"
NOTO_BOLD_TTC = _DEFAULT_FONT_DIR / "NotoSerifCJK-Bold.ttc"

WORD_JOINER = "\u2060"
COVER_CSS = """@page { margin: 0; }
html, body { margin: 0; padding: 0; height: 100%; }
.cover { margin: 0; padding: 0; text-align: center; page-break-inside: avoid; }
.cover-image { display: block; margin: 0 auto; width: auto; height: auto;
               max-width: 100%; max-height: 100vh; }
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _text_html(text: str) -> str:
    """Keep explicit source line breaks, including blank lines in operator files."""
    return _esc(text.replace("\r\n", "\n").replace("\r", "\n")).replace("\n", "<br/>")


def _content_anchor(preferred: str, used: Set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]", "_", preferred)
    if not candidate or not re.match(r"[A-Za-z_]", candidate):
        candidate = "line_" + candidate
    base = candidate
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _utterance_html(spk: str, txt: str, lang: str) -> str:
    if spk:
        colon = UI_STRINGS.get(lang, UI_STRINGS["zh"])["colon"]
        joiner = WORD_JOINER if colon == "：" else ""
        return f"{_esc(spk)}{colon}{joiner}{_text_html(txt)}"
    return _text_html(txt)


def _render_language_block(spk: str, txt: str, lang: str, is_translation: bool = False) -> str:
    epub_lang = EPUB_LANG_TAGS.get(lang, "zh-Hans")
    cls = "language-block translation" if is_translation else "language-block"
    inner = _utterance_html(spk, txt, lang)
    return f'<div class="{cls}" lang="{epub_lang}"><p class="utterance prose-paragraph">{inner}</p></div>'


def _render_monolingual_exchange(spk: str, txt: str, lang: str, cls: str, anchor: str) -> str:
    """Keep large single-language collections below boko's four-digit aid limit.

    One prose container replaces the exchange, language and paragraph wrappers.
    Explicit line breaks, the block anchor and branch depth remain on it.
    """
    epub_lang = EPUB_LANG_TAGS.get(lang, "zh-Hans")
    inner = _utterance_html(spk, txt, lang)
    return (f'<div class="{cls} language-block compact-prose" id="{_esc(anchor)}" '
            f'lang="{epub_lang}">{inner}</div>')


def render_book_xhtml(
    doc_title: str,
    sections: List[LinearSection],
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
) -> str:
    bilingual = bool(secondary_lang and secondary_lang != primary_lang)
    p_epub_lang = EPUB_LANG_TAGS.get(primary_lang, "zh-Hans")
    ui = UI_STRINGS.get(primary_lang, UI_STRINGS["zh"])
    scene_ids = [sec.scene_id for sec in sections]
    if len(scene_ids) != len(set(scene_ids)):
        raise ValueError("EPUB section IDs must be unique within a publication.")
    used_ids = set(scene_ids)

    parts: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{p_epub_lang}">'
        f"<head><title>{_esc(doc_title)}</title>"
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
        '<body><section class="reading-section">'
    ]

    for sec in sections:
        p_tag = localize_stage_tag(sec.raw_tag, primary_lang)
        p_title = sec.titles.get(primary_lang) or sec.titles.get("zh") or sec.scene_id

        level = max(1, min(sec.heading_level, 6))
        divider_class = " collection-divider" if sec.is_divider else ""
        head_parts = [f'<header class="section-head level-{level}{divider_class}" id="{_esc(sec.scene_id)}">']
        if p_tag:
            head_parts.append(f'<p class="section-number">{_esc(p_tag)}</p>')
        head_parts.append(f"<h{level}>{_esc(p_title)}</h{level}>")
        if bilingual and secondary_lang:
            s_title = sec.titles.get(secondary_lang) or ""
            if s_title and s_title != p_title:
                s_epub_lang = EPUB_LANG_TAGS.get(secondary_lang, "en")
                head_parts.append(f'<p class="subtitle" lang="{s_epub_lang}">{_esc(s_title)}</p>')
        head_parts.append("</header>")
        parts.append("".join(head_parts))

        for block_index, blk in enumerate(sec.blocks, start=1):
            if blk.kind == "utterance":
                p_txt = blk.texts.get(primary_lang) or ""
                p_spk = blk.speakers.get(primary_lang) or ""
                ex_cls = f"exchange depth-{blk.depth}" if blk.depth > 0 else "exchange"
                if not bilingual:
                    if p_txt:
                        anchor = _content_anchor(blk.line_id or f"{sec.scene_id}_block_{block_index}", used_ids)
                        parts.append(_render_monolingual_exchange(p_spk, p_txt, primary_lang, ex_cls, anchor))
                    continue
                lang_divs: List[str] = []
                if p_txt:
                    lang_divs.append(_render_language_block(p_spk, p_txt, primary_lang, is_translation=False))
                if bilingual and secondary_lang:
                    s_txt = blk.texts.get(secondary_lang) or ""
                    s_spk = blk.speakers.get(secondary_lang) or ""
                    if s_txt:
                        lang_divs.append(_render_language_block(s_spk, s_txt, secondary_lang, is_translation=bool(p_txt)))
                if not lang_divs:
                    continue
                anchor = _content_anchor(blk.line_id or f"{sec.scene_id}_block_{block_index}", used_ids)
                parts.append(f'<div class="{ex_cls}" id="{anchor}">{"".join(lang_divs)}</div>')

            elif blk.kind == "choices":
                li_items: List[str] = []
                for option_index, opt in enumerate(blk.options, start=1):
                    opt_divs: List[str] = []
                    p_opt = opt["texts"].get(primary_lang) or ""
                    anchor = _content_anchor(
                        opt.get("id") or f"{sec.scene_id}_block_{block_index}_option_{option_index}", used_ids
                    )
                    if not bilingual:
                        li_items.append(f'<li>{_render_monolingual_exchange("", p_opt, primary_lang, "exchange", anchor)}</li>')
                        continue
                    if p_opt:
                        opt_divs.append(_render_language_block("", p_opt, primary_lang, is_translation=False))
                    if bilingual and secondary_lang:
                        s_opt = opt["texts"].get(secondary_lang) or ""
                        if s_opt:
                            opt_divs.append(_render_language_block("", s_opt, secondary_lang, is_translation=bool(p_opt)))
                    li_items.append(f'<li><div class="exchange" id="{anchor}">{"".join(opt_divs)}</div></li>')
                parts.append(f'<ol class="choices">{"".join(li_items)}</ol>')

            elif blk.kind == "branch_notice":
                label = ui["branch_fmt"].format(n=blk.branch_index)
                parts.append(f'<p class="notice">{_esc(label)}</p>')

            elif blk.kind == "shared_notice":
                parts.append(f'<p class="notice">{_esc(ui["shared_cont"])}</p>')

    parts.append("</section></body></html>")
    return "".join(parts)


def _navigation_nodes(
    doc_title: str,
    sections: List[LinearSection],
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
    section_hrefs: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    bilingual = bool(secondary_lang and secondary_lang != primary_lang)

    # A heading belongs to the closest preceding heading at a shallower level.
    # This also handles a document that starts at level 2 or skips a level.
    roots: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = []
    ids: Set[str] = set()
    for sec in sections:
        if not sec.scene_id or sec.scene_id in ids:
            raise ValueError("EPUB section IDs must be nonempty and unique.")
        ids.add(sec.scene_id)
        if not sec.include_in_toc:
            continue
        p_tag = localize_stage_tag(sec.raw_tag, primary_lang)
        p_title = sec.titles.get(primary_lang) or sec.titles.get("zh") or sec.scene_id
        # Match arena/001-黑暗时代·上.epub nav.xhtml: Interlude ('幕间') omits prefix in nav TOC
        if sec.raw_tag == "幕间" or not p_tag:
            label = p_title
        else:
            label = f"{p_tag} · {p_title}"
        if bilingual and secondary_lang:
            s_title = sec.titles.get(secondary_lang) or ""
            if s_title and s_title != p_title:
                label = f"{label} / {s_title}"
        filename = (section_hrefs or {}).get(sec.scene_id, "book.xhtml")
        node: Dict[str, Any] = {
            "level": max(1, min(sec.heading_level, 6)),
            "label": label,
            "href": f"{filename}#{sec.scene_id}",
            "is_collection": sec.is_divider and sec.scene_id.startswith("collection_"),
            "children": [],
        }
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def _overview_categories(roots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [node for node in roots if node["is_collection"] and node["children"]]


def _contents_link(label: str) -> Dict[str, Any]:
    return {"href": "nav.xhtml#toc", "label": label, "children": []}


def render_nav_xhtml(
    doc_title: str,
    sections: List[LinearSection],
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
    section_hrefs: Optional[Dict[str, str]] = None,
) -> str:
    p_epub_lang = EPUB_LANG_TAGS.get(primary_lang, "zh-Hans")
    ui = UI_STRINGS.get(primary_lang, UI_STRINGS["zh"])
    first_id = sections[0].scene_id if sections else ""
    roots = _navigation_nodes(doc_title, sections, primary_lang, secondary_lang, section_hrefs)

    def render_link(node: Dict[str, Any]) -> str:
        return f'<a href="{_esc(node["href"])}">{_esc(node["label"])}</a>'

    def render_list(nodes: List[Dict[str, Any]], depth: int = 1) -> str:
        items = []
        for node in nodes:
            children = render_list(node["children"], depth + 1) if node["children"] else ""
            items.append(f'<li>{render_link(node)}{children}</li>')
        return f'<ol class="toc-level-{depth}">{"".join(items)}</ol>'

    first_file = (section_hrefs or {}).get(first_id, "book.xhtml")
    title = f'<h1 id="toc">{_esc(ui["toc_heading"])}</h1>'
    categories = _overview_categories(roots)
    overview = ""
    if categories:
        links = "".join(f'<li>{render_link(node)}</li>' for node in categories)
        details = _esc(ui["toc_details"])
        overview = (
            f'{title}<section class="quick-index" aria-labelledby="toc-overview">'
            f'<h2 id="toc-overview">{_esc(ui["toc_overview"])}</h2><ul>{links}</ul>'
            f'<p><a href="#toc-details">{details}</a></p></section>'
        )
        title = f'<h2 id="toc-details">{details}</h2>'
    else:
        roots.insert(0, _contents_link(ui["toc_heading"]))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{p_epub_lang}">'
        f"<head><title>{_esc(ui['toc_heading'])}</title>"
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
        f'<body>{overview}<nav epub:type="toc">{title}'
        f'{render_list(roots)}</nav>'
        '<nav epub:type="landmarks" hidden="hidden"><ol>'
        f'<li><a epub:type="cover" href="cover.xhtml">{_esc(ui["cover_landmark"])}</a></li>'
        f'<li><a epub:type="toc" href="nav.xhtml#toc">{_esc(ui["toc_heading"])}</a></li>'
        f'<li><a epub:type="bodymatter" href="{_esc(first_file)}#{_esc(first_id)}">{_esc(ui["story_heading"])}</a></li>'
        "</ol></nav></body></html>"
    )


def render_ncx(
    doc_title: str,
    sections: List[LinearSection],
    uid: str,
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
    section_hrefs: Optional[Dict[str, str]] = None,
) -> str:
    """EPUB 2-compatible navigation for readers that ignore EPUB 3 nav.xhtml."""
    roots = _navigation_nodes(doc_title, sections, primary_lang, secondary_lang, section_hrefs)
    ui = UI_STRINGS.get(primary_lang, UI_STRINGS["zh"])
    if not _overview_categories(roots):
        roots.insert(0, _contents_link(ui["toc_heading"]))
    play_order = 0
    max_depth = 1

    def render_points(nodes: List[Dict[str, Any]], depth: int = 1) -> str:
        nonlocal play_order, max_depth
        max_depth = max(max_depth, depth)
        points: List[str] = []
        for node in nodes:
            play_order += 1
            current_order = play_order
            children = render_points(node["children"], depth + 1) if node["children"] else ""
            points.append(
                f'<navPoint id="navPoint-{current_order}" playOrder="{current_order}">'
                f'<navLabel><text>{_esc(node["label"])}</text></navLabel>'
                f'<content src="{_esc(node["href"])}"/>{children}</navPoint>'
            )
        return "".join(points)

    nav_points = render_points(roots)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="{_esc(uid)}"/>'
        f'<meta name="dtb:depth" content="{max_depth}"/>'
        '<meta name="dtb:totalPageCount" content="0"/>'
        '<meta name="dtb:maxPageNumber" content="0"/></head>'
        f'<docTitle><text>{_esc(doc_title)}</text></docTitle>'
        f'<navMap>{nav_points}</navMap></ncx>'
    )


def render_cover_xhtml(doc_title: str, primary_lang: str = "zh") -> str:
    epub_lang = EPUB_LANG_TAGS.get(primary_lang, "zh-Hans")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{epub_lang}">'
        f"<head><title>{_esc(doc_title)}</title>"
        '<link rel="stylesheet" type="text/css" href="cover.css"/></head>'
        '<body><section epub:type="cover" class="cover" id="cover">'
        f'<img class="cover-image" src="cover.png" alt="{_esc(doc_title)}"/>'
        "</section></body></html>"
    )


def _subset_font(
    src_font: Path,
    dst_font: Path,
    unicodes_hex: str,
    font_number: Optional[int] = None,
) -> None:
    if not src_font.is_file():
        raise FileNotFoundError(f"Font file not found: {src_font}")
    dst_font.parent.mkdir(parents=True, exist_ok=True)
    from fontTools import __version__ as fonttools_version
    from fontTools.ttLib import TTFont
    digest = hashlib.sha256()
    with src_font.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(repr((font_number, unicodes_hex, fonttools_version,
                        "recommended-glyphs,notdef-glyph,notdef-outline:v1")).encode())
    cached = cache_root() / "font-subsets-v1" / (digest.hexdigest() + dst_font.suffix)
    metrics = CURRENT_MEASUREMENTS.get()
    if cached.is_file():
        try:
            with TTFont(cached) as font:
                font.getBestCmap()
            dst_font.write_bytes(cached.read_bytes())
            if metrics:
                metrics.count("font_cache_hits")
            return
        except Exception:
            # Rebuild an unreadable cache; source/fontTools errors still surface below.
            pass
    with tempfile.TemporaryDirectory(prefix="terra_subset_") as temporary:
        unicode_file = Path(temporary) / "unicodes.txt"
        unicode_file.write_text(unicodes_hex, encoding="ascii")
        cmd = [
            sys.executable,
            "-m",
            "fontTools.subset",
            str(src_font),
            f"--output-file={dst_font}",
            # A full collection can exceed Windows/Linux command-line limits if
            # its thousands of Unicode code points are passed as one argument.
            f"--unicodes-file={unicode_file}",
            "--recommended-glyphs",
            "--notdef-glyph",
            "--notdef-outline",
        ]
        if font_number is not None:
            cmd.append(f"--font-number={font_number}")
        try:
            with measured("font_subset_tasks"):
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
            if metrics:
                metrics.count("font_subset_processes")
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Font subsetting failed for {src_font.name}:\n{detail}") from exc
    atomic_write(cached, dst_font.read_bytes())


def _noto_font(lang: str, weight: str) -> Tuple[Path, Optional[int]]:
    """Find an installed Noto collection or an explicitly supplied language face."""
    configured = os.environ.get("TERRA_NOTO_FONT_DIR")
    roots: List[Path] = []
    if configured:
        font_dir = Path(configured).expanduser().resolve()
        if not font_dir.is_dir():
            raise FileNotFoundError(f"TERRA_NOTO_FONT_DIR is not a directory: {font_dir}")
        roots.append(font_dir)
    roots.append(NOTO_REGULAR_TTC.parent)
    short_code = {"zh": "SC", "tw": "TC", "ja": "JP", "ko": "KR"}[lang]
    for root in roots:
        collection = root / f"NotoSerifCJK-{weight}.ttc"
        if collection.is_file():
            return collection, NOTO_TTC_INDEX[lang]
        stems = (f"NotoSerifCJK{short_code.lower()}-{weight}", f"NotoSerif{short_code}-{weight}")
        for stem in stems:
            for extension in (".otf", ".ttf"):
                face = root / f"{stem}{extension}"
                if face.is_file():
                    return face, None
    raise FileNotFoundError(
        f"Noto Serif CJK {short_code} {weight} was not found. "
        "Install fonts-noto-cjk or set TERRA_NOTO_FONT_DIR to a folder with the Noto font files."
    )


def _build_fonts_and_css(
    used_chars: Set[str],
    active_langs: List[str],
    out_fonts_dir: Path,
) -> Tuple[str, List[Tuple[str, str]]]:
    out_fonts_dir.mkdir(parents=True, exist_ok=True)
    base_chars = used_chars | set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,:;!?-'\"()[]/·—… ")
    codepoints = sorted(ord(c) for c in base_chars if ord(c) >= 0x20)
    unicodes_hex = ",".join(f"U+{cp:04X}" for cp in codepoints)

    manifest_fonts: List[Tuple[str, str]] = []
    subset_tasks = []

    # 1. Always embed subsetted Latin fonts (EB Garamond)
    latin_specs = [
        ("font-latin", "latin.ttf", FONTS_DIR / "EBGaramond-Regular.ttf"),
        ("font-latin-semibold", "latin-semibold.ttf", FONTS_DIR / "EBGaramond-SemiBold.ttf"),
        ("font-latin-italic", "latin-italic.ttf", FONTS_DIR / "EBGaramond-Italic.ttf"),
    ]
    for item_id, fname, src_path in latin_specs:
        subset_tasks.append((src_path, out_fonts_dir / fname, unicodes_hex, None))
        manifest_fonts.append((item_id, f"fonts/{fname}"))

    # 2. Subset CJK fonts for each active CJK language (zh, tw, ja, ko)
    cjk_langs = list(dict.fromkeys(l for l in active_langs if l in ("zh", "tw", "ja", "ko")))
    if not cjk_langs and any(0x2E80 <= ord(char) <= 0x9FFF for char in used_chars):
        # Missing translations may legitimately fall back to Chinese in an
        # otherwise English edition; keep that source text readable as well.
        cjk_langs.append("zh")
    cjk_families: List[str] = []
    font_faces: List[str] = [
        '@font-face{font-family:"Terra Latin";src:url("fonts/latin.ttf");font-style:normal;font-weight:400;}',
        '@font-face{font-family:"Terra Latin";src:url("fonts/latin-semibold.ttf");font-style:normal;font-weight:600;}',
        '@font-face{font-family:"Terra Latin";src:url("fonts/latin-italic.ttf");font-style:italic;font-weight:400;}',
    ]
    lang_specific_rules: List[str] = []

    for lang in cjk_langs:
        fam_name = f"Terra {lang.upper()}"
        cjk_families.append(f'"{fam_name}"')
        regular, regular_index = _noto_font(lang, "Regular")
        bold, bold_index = _noto_font(lang, "Bold")
        regular_ext = "ttf" if regular.suffix.lower() == ".ttf" else "otf"
        bold_ext = "ttf" if bold.suffix.lower() == ".ttf" else "otf"
        reg_name = f"cjk-{lang}.{regular_ext}"
        bold_name = f"cjk-{lang}-semibold.{bold_ext}"
        subset_tasks.append((regular, out_fonts_dir / reg_name, unicodes_hex, regular_index))
        subset_tasks.append((bold, out_fonts_dir / bold_name, unicodes_hex, bold_index))

        manifest_fonts.append((f"font-cjk-{lang}", f"fonts/{reg_name}"))
        manifest_fonts.append((f"font-cjk-{lang}-semibold", f"fonts/{bold_name}"))

        font_faces.append(
            f'@font-face{{font-family:"{fam_name}";src:url("fonts/{reg_name}");font-style:normal;font-weight:400;}}'
        )
        font_faces.append(
            f'@font-face{{font-family:"{fam_name}";src:url("fonts/{bold_name}");font-style:normal;font-weight:600;}}'
        )
        epub_tag = EPUB_LANG_TAGS[lang]
        if len(cjk_langs) > 1:
            lang_specific_rules.append(f':lang({epub_tag}) {{ font-family: "{fam_name}", "Terra Latin", serif; }}')

    with measured("font_subset_wall"):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(copy_context().run, _subset_font, *task) for task in subset_tasks]
            for future in futures:
                future.result()
    body_stack = ", ".join([*cjk_families, '"Terra Latin"', "serif"])
    css_template = STYLE_TEMPLATE_PATH.read_text(encoding="utf-8")
    css = css_template.replace("__BODY_FONT_STACK__", body_stack)
    if lang_specific_rules:
        css += "\n" + "\n".join(lang_specific_rules) + "\n"
    css += "\n" + "\n".join(font_faces) + "\n"
    return css, manifest_fonts


def _section_documents(sections: List[LinearSection]) -> Iterator[List[LinearSection]]:
    """Keep collection dividers with their first chapter, then split at chapters."""
    pending: List[LinearSection] = []
    for section in sections:
        pending.append(section)
        if not section.is_divider:
            yield pending
            pending = []
    if pending:
        yield pending


def write_epub(
    output_path: Path,
    volume_titles: Dict[str, str],
    sections: List[LinearSection],
    cover_png_bytes: bytes,
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
) -> Path:
    bilingual = bool(secondary_lang and secondary_lang != primary_lang)
    active_langs = [primary_lang] + ([secondary_lang] if bilingual and secondary_lang else [])
    ui = UI_STRINGS.get(primary_lang, UI_STRINGS["zh"])

    p_vol = volume_titles.get(primary_lang) or volume_titles.get("zh") or ""
    if bilingual and secondary_lang:
        s_vol = volume_titles.get(secondary_lang) or ""
        doc_title = f"{p_vol} / {s_vol}" if s_vol and s_vol != p_vol else p_vol
    else:
        doc_title = p_vol

    if not sections:
        raise ValueError("Cannot write an EPUB without sections.")
    scene_ids = [sec.scene_id for sec in sections]
    if any(not value for value in scene_ids) or len(set(scene_ids)) != len(scene_ids):
        raise ValueError("EPUB section IDs must be nonempty and unique.")
    first_scene_id = sections[0].scene_id
    cover_xhtml = render_cover_xhtml(doc_title, primary_lang=primary_lang)
    if not cover_png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("EPUB requires a nonempty PNG cover image.")

    with tempfile.TemporaryDirectory(prefix="terra_epub_") as tmpdir:
        tmp = Path(tmpdir)
        oebps = tmp / "OEBPS"
        oebps.mkdir(parents=True, exist_ok=True)

        used_chars = set(cover_xhtml)
        section_hrefs: Dict[str, str] = {}
        documents: List[Tuple[str, str]] = []
        content_hash = hashlib.sha256()
        content_hash.update(cover_xhtml.encode("utf-8") + cover_png_bytes)
        for index, group in enumerate(_section_documents(sections), start=1):
            item_id = "book" if index == 1 else f"section-{index:06d}"
            filename = f"{item_id}.xhtml"
            for section in group:
                section_hrefs[section.scene_id] = filename
            chapter = render_book_xhtml(doc_title, group, primary_lang, secondary_lang)
            chapter_bytes = chapter.encode("utf-8")
            (oebps / filename).write_bytes(chapter_bytes)
            used_chars.update(chapter)
            content_hash.update(filename.encode("ascii") + b"\0" + chapter_bytes)
            documents.append((item_id, filename))

        nav_xhtml = render_nav_xhtml(
            doc_title, sections, primary_lang, secondary_lang, section_hrefs=section_hrefs
        )
        used_chars.update(nav_xhtml)
        content_hash.update(nav_xhtml.encode("utf-8"))
        uid_hash = content_hash.hexdigest()
        uid = f"urn:sha256:{uid_hash}"
        toc_ncx = render_ncx(
            doc_title,
            sections,
            uid,
            primary_lang,
            secondary_lang,
            section_hrefs=section_hrefs,
        )
        css_text, manifest_fonts = _build_fonts_and_css(used_chars, active_langs, oebps / "fonts")

        license_files = sorted(LICENSES_DIR.glob("OFL-*.txt"))
        manifest_licenses = [
            (f"license-{lf.stem}", f"licenses/{lf.name}", lf.read_bytes())
            for lf in license_files
        ]

        font_items_xml = "".join(
            f'<item id="{fid}" href="{href}" media-type="font/{Path(href).suffix[1:]}"/>'
            for fid, href in manifest_fonts
        )
        lic_items_xml = "".join(
            f'<item id="{lid}" href="{href}" media-type="text/plain"/>'
            for lid, href, _ in manifest_licenses
        )
        document_items_xml = "".join(
            f'<item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>'
            for item_id, filename in documents
        )
        document_spine_xml = "".join(f'<itemref idref="{item_id}"/>' for item_id, _ in documents)
        languages_xml = "".join(
            f'<dc:language>{EPUB_LANG_TAGS.get(lang, lang)}</dc:language>'
            for lang in active_langs
        )
        modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        package_opf = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:identifier id=\"id\">{uid}</dc:identifier>"
            f"<dc:title>{_esc(doc_title)}</dc:title>"
            f"{languages_xml}"
            "<dc:creator>泰拉文库 / Terra Library</dc:creator>"
            f"<dc:rights>{_esc(ui['opf_rights'])}</dc:rights>"
            f'<meta property="dcterms:modified">{modified}</meta>'
            '<meta name="cover" content="cover-image"/>'
            "</metadata>"
            "<manifest>"
            '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            f"{document_items_xml}"
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '<item id="css" href="style.css" media-type="text/css"/>'
            '<item id="cover-css" href="cover.css" media-type="text/css"/>'
            '<item id="cover-image" href="cover.png" media-type="image/png" properties="cover-image"/>'
            f"{font_items_xml}"
            f"{lic_items_xml}"
            "</manifest>"
            '<spine toc="ncx">'
            '<itemref idref="cover"/>'
            '<itemref idref="nav"/>'
            f"{document_spine_xml}"
            "</spine>"
            '<guide>'
            f'<reference type="cover" title="{_esc(ui["cover_landmark"])}" href="cover.xhtml"/>'
            f'<reference type="toc" title="{_esc(ui["toc_heading"])}" href="nav.xhtml#toc"/>'
            f'<reference type="text" title="{_esc(ui["story_heading"])}" href="{_esc(section_hrefs[first_scene_id])}#{_esc(first_scene_id)}"/>'
            '</guide>'
            "</package>"
        )

        container_xml = (
            '<?xml version="1.0"?>'
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            "<rootfiles>"
            '<rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles>"
            "</container>"
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w") as zf:
            # EPUB 3 spec: mimetype MUST be first entry, uncompressed, without extra fields
            mi = zipfile.ZipInfo("mimetype")
            mi.compress_type = zipfile.ZIP_STORED
            zf.writestr(mi, b"application/epub+zip")

            zf.writestr("META-INF/container.xml", container_xml.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/package.opf", package_opf.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/cover.xhtml", cover_xhtml.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/nav.xhtml", nav_xhtml.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
            for _, filename in documents:
                zf.write(oebps / filename, f"OEBPS/{filename}", compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/toc.ncx", toc_ncx.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/style.css", css_text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/cover.png", cover_png_bytes, compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/cover.css", COVER_CSS.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)

            for _, rel_href in manifest_fonts:
                zf.write(oebps / rel_href, f"OEBPS/{rel_href}", compress_type=zipfile.ZIP_DEFLATED)

            for _, rel_href, raw_lic in manifest_licenses:
                zf.writestr(f"OEBPS/{rel_href}", raw_lic, compress_type=zipfile.ZIP_DEFLATED)

    return output_path
