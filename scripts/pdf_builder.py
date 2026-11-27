"""Typst 0.15.1 native A4 PDF & cover PNG compiler."""

from __future__ import annotations
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .dag_linearizer import LinearSection
from .i18n import TYPST_LANG_CONFIG, UI_STRINGS, format_utterance_line, get_edition_badge, localize_stage_tag
from .runtime import atomic_write, cache_root, measured

PUBLISHER_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = PUBLISHER_DIR / "templates" / "terra_v4.typ"
FONTS_DIR = PUBLISHER_DIR / "assets" / "fonts"


def ensure_typst_binary(download: bool = True) -> Path:
    """Return usable Typst 0.15.1 binary path; auto-downloads matching OS/arch binary if needed."""
    configured_binary = os.environ.get("TERRA_TYPST_BIN")
    if configured_binary:
        binary = Path(configured_binary).expanduser().resolve()
        if not binary.is_file():
            raise FileNotFoundError(f"TERRA_TYPST_BIN does not point to a file: {binary}")
        # An explicit local executable must never fall back to a network download.
        return binary

    sys_typst = shutil.which("typst")
    if sys_typst:
        return Path(sys_typst)

    sys_name = platform.system().lower()
    arch = platform.machine().lower()
    if arch not in ("x86_64", "amd64", "aarch64", "arm64") or (
        sys_name == "windows" and arch not in ("x86_64", "amd64")
    ):
        raise RuntimeError(
            f"Unsupported platform for auto-downloading Typst: {sys_name}/{arch}; set TERRA_TYPST_BIN."
        )
    if sys_name == "linux":
        target = "aarch64-unknown-linux-musl" if arch in ("aarch64", "arm64") else "x86_64-unknown-linux-musl"
        ext = "tar.xz"
    elif sys_name == "darwin":
        target = "aarch64-apple-darwin" if arch in ("aarch64", "arm64") else "x86_64-apple-darwin"
        ext = "tar.xz"
    elif sys_name == "windows":
        target = "x86_64-pc-windows-msvc"
        ext = "zip"
    else:
        raise RuntimeError(f"Unsupported platform for auto-downloading Typst: {sys_name}/{arch}")

    cached_binary = cache_root() / "typst" / "0.15.1" / target / ("typst.exe" if os.name == "nt" else "typst")
    if cached_binary.is_file():
        try:
            result = subprocess.run([str(cached_binary), "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and "0.15.1" in result.stdout:
                return cached_binary
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not download:
        raise FileNotFoundError("Typst is not installed or cached; set TERRA_TYPST_BIN or install Typst")
    url = f"https://github.com/typst/typst/releases/download/v0.15.1/typst-{target}.{ext}"
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / f"typst.{ext}"
        urllib.request.urlretrieve(url, archive_path)
        if ext == "zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                member = next(name for name in zf.namelist() if name.endswith("/typst.exe") or name == "typst.exe")
                binary_data = zf.read(member)
        else:
            with tarfile.open(archive_path, "r:xz") as tf:
                member = next(member for member in tf.getmembers() if member.isfile() and member.name.endswith("/typst"))
                with tf.extractfile(member) as stream:
                    binary_data = stream.read()
        bin_name = "typst.exe" if os.name == "nt" else "typst"
        extracted = Path(tmpdir) / bin_name
        extracted.write_bytes(binary_data)
        if os.name != "nt":
            extracted.chmod(0o755)
        result = subprocess.run([str(extracted), "--version"], check=True, capture_output=True, text=True, timeout=5)
        if "0.15.1" not in result.stdout:
            raise RuntimeError("Downloaded Typst did not report the required version 0.15.1")
        atomic_write(cached_binary, binary_data)
        if os.name != "nt":
            cached_binary.chmod(0o755)
    return cached_binary


def build_typst_payload(
    volume_titles: Dict[str, str],
    sections: List[LinearSection],
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
) -> Dict[str, Any]:
    bilingual = bool(secondary_lang and secondary_lang != primary_lang)
    s_lang = secondary_lang if bilingual and secondary_lang else primary_lang

    p_cfg = TYPST_LANG_CONFIG.get(primary_lang, TYPST_LANG_CONFIG["zh"])
    s_cfg = TYPST_LANG_CONFIG.get(s_lang, TYPST_LANG_CONFIG["en"])
    ui = UI_STRINGS.get(primary_lang, UI_STRINGS["zh"])

    p_vol = volume_titles.get(primary_lang) or volume_titles.get("zh") or ""
    s_vol = volume_titles.get(s_lang) or "" if bilingual else ""

    sec_items: List[Dict[str, Any]] = []
    for sec in sections:
        p_title = sec.titles.get(primary_lang) or sec.titles.get("zh") or sec.scene_id
        s_title = sec.titles.get(s_lang) or "" if bilingual else ""
        p_tag = localize_stage_tag(sec.raw_tag, primary_lang)

        out_blocks: List[Dict[str, Any]] = []
        for blk in sec.blocks:
            if blk.kind == "utterance":
                txt_p = blk.texts.get(primary_lang) or ""
                txt_s = blk.texts.get(s_lang) or "" if bilingual else ""
                if not txt_p and not txt_s:
                    continue
                if txt_p:
                    txt_p = format_utterance_line(blk.speakers.get(primary_lang) or "", txt_p, primary_lang)
                if txt_s:
                    txt_s = format_utterance_line(blk.speakers.get(s_lang) or "", txt_s, s_lang)
                out_blocks.append({
                    "kind": "utterance",
                    "depth": blk.depth,
                    "txt_p": txt_p,
                    "txt_s": txt_s,
                })
            elif blk.kind == "choices":
                out_blocks.append({
                    "kind": "choices",
                    "depth": blk.depth,
                    "options": [
                        {
                            "index": opt["index"],
                            "txt_p": opt["texts"].get(primary_lang) or "",
                            "txt_s": opt["texts"].get(s_lang) or "" if bilingual else "",
                        }
                        for opt in blk.options
                    ],
                })
            elif blk.kind == "branch_notice":
                out_blocks.append({
                    "kind": "branch_notice",
                    "depth": blk.depth,
                    "label": ui["branch_fmt"].format(n=blk.branch_index),
                })
            elif blk.kind == "shared_notice":
                out_blocks.append({
                    "kind": "shared_notice",
                    "depth": blk.depth,
                    "label": ui["shared_cont"],
                })

        sec_items.append({
            "scene_id": sec.scene_id,
            "title_primary": p_title,
            "title_secondary": s_title,
            "tag_primary": p_tag,
            "heading_level": max(1, min(sec.heading_level, 6)),
            "is_divider": sec.is_divider,
            "blocks": out_blocks,
        })

    doc_title = f"{p_vol} / {s_vol}" if bilingual and s_vol and s_vol != p_vol else p_vol
    return {
        "doc_title": doc_title,
        "volume_title_primary": p_vol,
        "volume_title_secondary": s_vol,
        "edition_badge": get_edition_badge(primary_lang, secondary_lang if bilingual else None),
        "primary_lang": primary_lang,
        "secondary_lang": s_lang,
        "bilingual": bilingual,
        "primary_cjk_font": p_cfg["cjk_font"],
        "secondary_cjk_font": s_cfg["cjk_font"],
        "primary_typst_lang": p_cfg["lang"],
        "primary_typst_region": p_cfg["region"],
        "secondary_typst_lang": s_cfg["lang"],
        "secondary_typst_region": s_cfg["region"],
        "ui": ui,
        "sections": sec_items,
    }


def compile_pdf_and_cover(
    pdf_output_path: Optional[Path],
    cover_png_path: Optional[Path],
    volume_titles: Dict[str, str],
    sections: List[LinearSection],
    primary_lang: str = "zh",
    secondary_lang: Optional[str] = None,
    preview_pages: Optional[str] = None,
    preview_png_pattern: Optional[Path] = None,
) -> Tuple[Optional[Path], Optional[Path]]:
    payload = build_typst_payload(
        volume_titles=volume_titles,
        sections=sections if pdf_output_path is not None or preview_pages else [],
        primary_lang=primary_lang,
        secondary_lang=secondary_lang,
    )

    with tempfile.TemporaryDirectory(prefix="terra_typst_") as tmpdir:
        tmp = Path(tmpdir)
        typ_copy = tmp / "terra_v4.typ"
        shutil.copy2(TEMPLATE_PATH, typ_copy)
        data_file = tmp / "data.json"
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        typst_exe = ensure_typst_binary()
        base_cmd = [
            str(typst_exe),
            "compile",
            "--font-path",
            str(FONTS_DIR),
        ]
        configured_fonts = os.environ.get("TERRA_NOTO_FONT_DIR")
        if configured_fonts:
            font_dir = Path(configured_fonts).expanduser().resolve()
            if not font_dir.is_dir():
                raise FileNotFoundError(f"TERRA_NOTO_FONT_DIR is not a directory: {font_dir}")
            base_cmd.extend(["--font-path", str(font_dir)])

        def compile_to(arguments: List[str], data_name: str = "data.json") -> None:
            try:
                with measured("typst"):
                    subprocess.run(
                        [*base_cmd, "--input", f"data={data_name}", *arguments],
                        check=True, capture_output=True, text=True, encoding="utf-8",
                    )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                raise RuntimeError(f"Typst compilation failed:\n{detail}") from exc

        if pdf_output_path is not None:
            pdf_output_path.parent.mkdir(parents=True, exist_ok=True)
            compile_to([str(typ_copy), str(pdf_output_path)])

        if cover_png_path is not None:
            cover_png_path.parent.mkdir(parents=True, exist_ok=True)
            # A cover is independent of the story body. Avoid typesetting a whole
            # multi-volume collection a second time just to rasterize its first page.
            cover_payload = {**payload, "sections": []}
            (tmp / "cover_data.json").write_text(
                json.dumps(cover_payload, ensure_ascii=False), encoding="utf-8"
            )
            compile_to(
                [
                    "--pages",
                    "1",
                    "--ppi",
                    "144",
                    "--format",
                    "png",
                    str(typ_copy),
                    str(cover_png_path),
                ],
                data_name="cover_data.json",
            )

        if preview_pages and preview_png_pattern is not None:
            preview_png_pattern.parent.mkdir(parents=True, exist_ok=True)
            compile_to(
                [
                    "--pages",
                    preview_pages,
                    "--ppi",
                    "144",
                    "--format",
                    "png",
                    str(typ_copy),
                    str(preview_png_pattern),
                ],
            )

    return pdf_output_path, cover_png_path
