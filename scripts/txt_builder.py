"""Readable TXT publications with nested collection and chapter headings."""

from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional

from .dag_linearizer import LinearSection
from .i18n import UI_STRINGS, format_utterance_line, localize_stage_tag


def render_txt(
    volume_titles: Dict[str, str],
    sections: List[LinearSection],
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
) -> str:
    bilingual = bool(secondary_lang and secondary_lang != primary_lang)
    ui = UI_STRINGS.get(primary_lang, UI_STRINGS["zh"])

    p_vol_title = volume_titles.get(primary_lang) or volume_titles.get("zh") or ""
    if bilingual and secondary_lang:
        s_vol_title = volume_titles.get(secondary_lang) or ""
        vol_header = f"{p_vol_title} / {s_vol_title}" if s_vol_title and s_vol_title != p_vol_title else p_vol_title
    else:
        vol_header = p_vol_title

    lines: List[str] = [
        "泰拉文库 / Terra Library",
        vol_header,
        "",
        ui["toc_heading"],
    ]

    for sec in sections:
        p_tag = localize_stage_tag(sec.raw_tag, primary_lang)
        p_title = sec.titles.get(primary_lang) or sec.titles.get("zh") or sec.scene_id
        toc_entry = f"{p_tag} · {p_title}" if p_tag else p_title
        if bilingual and secondary_lang:
            s_title = sec.titles.get(secondary_lang) or ""
            if s_title and s_title != p_title:
                toc_entry = f"{toc_entry} / {s_title}"
        level = max(1, min(sec.heading_level, 6))
        lines.append("  " * (level - 1) + toc_entry)

    lines.extend([
        "",
        ui["story_heading"],
    ])

    for sec in sections:
        p_tag = localize_stage_tag(sec.raw_tag, primary_lang)
        p_title = sec.titles.get(primary_lang) or sec.titles.get("zh") or sec.scene_id
        level = max(1, min(sec.heading_level, 6))
        if sec.is_divider:
            sep = "#" * 64 if level == 1 else "-" * 56
        else:
            sep = "=" * 48

        lines.extend(["", "", sep])
        if bilingual and secondary_lang:
            s_title = sec.titles.get(secondary_lang) or ""
            if s_title and s_title != p_title:
                lines.append(f"{p_title} / {s_title}")
            else:
                lines.append(p_title)
        else:
            lines.append(p_title)
        if p_tag:
            lines.append(p_tag)
        lines.extend([sep, ""])

        body_chunks: List[str] = []
        for blk in sec.blocks:
            if blk.kind == "utterance":
                p_text = blk.texts.get(primary_lang) or ""
                p_spk = blk.speakers.get(primary_lang) or ""
                chunk_lines: List[str] = []
                if p_text:
                    chunk_lines.append(format_utterance_line(p_spk, p_text, primary_lang))
                if bilingual and secondary_lang:
                    s_text = blk.texts.get(secondary_lang) or ""
                    s_spk = blk.speakers.get(secondary_lang) or ""
                    if s_text:
                        chunk_lines.append(format_utterance_line(s_spk, s_text, secondary_lang))
                if chunk_lines:
                    body_chunks.append("\n".join(chunk_lines))

            elif blk.kind == "choices":
                for opt in blk.options:
                    idx = opt["index"]
                    opt_lines = [f"{idx}."]
                    p_opt = opt["texts"].get(primary_lang) or ""
                    if p_opt:
                        opt_lines.append(p_opt)
                    if bilingual and secondary_lang:
                        s_opt = opt["texts"].get(secondary_lang) or ""
                        if s_opt:
                            opt_lines.append(s_opt)
                    body_chunks.append("\n".join(opt_lines))

            elif blk.kind == "branch_notice":
                body_chunks.append(ui["branch_fmt"].format(n=blk.branch_index))

            elif blk.kind == "shared_notice":
                body_chunks.append(ui["shared_cont"])

        lines.append("\n\n".join(body_chunks))

    lines.extend([
        "",
        "",
        ui["txt_rights"],
        "",
    ])
    return "\n".join(lines)


def write_txt(
    output_path: Path,
    volume_titles: Dict[str, str],
    sections: List[LinearSection],
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_txt(volume_titles, sections, primary_lang=primary_lang, secondary_lang=secondary_lang)
    with open(output_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)
    return output_path
