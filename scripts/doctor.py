"""Read-only environment diagnostics; never download or create directories."""
from __future__ import annotations
import importlib.util
import os
import subprocess
from pathlib import Path

from .epub_builder import _noto_font, FONTS_DIR, STYLE_TEMPLATE_PATH
from .pdf_builder import ensure_typst_binary, TEMPLATE_PATH


def _writable_ancestor(path):
    path = Path(path).expanduser().resolve()
    while not path.exists() and path.parent != path:
        path = path.parent
    return path.is_dir() and os.access(path, os.W_OK)


def check_environment(provider, languages, formats, output):
    checks = []
    def add(label, ok, detail=""):
        checks.append((label, bool(ok), str(detail)))
    add("Output directory", _writable_ancestor(output), output)
    add("Cache directory", _writable_ancestor(provider.cache_dir), provider.cache_dir)
    if provider.repo_dir:
        for lang in languages:
            root = provider._local_gamedata_root(lang)
            add(f"Local data {lang}", root is not None and (root / "excel").is_dir(), root or "missing locale")
            if root:
                tables = [name for name in ("story_review_table.json", "handbook_info_table.json", "uniequip_table.json")
                          if (root / "excel" / name).is_file()]
                add(f"Readable source tables {lang}", bool(tables), ", ".join(tables) or "no content tables")
    else:
        add("Remote source", True, "configured; network is not contacted")
    if "pdf" in formats or "epub" in formats:
        add("Typst template", TEMPLATE_PATH.is_file(), TEMPLATE_PATH)
        try:
            binary = ensure_typst_binary(download=False)
            result = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=5)
            add("Typst", result.returncode == 0, result.stdout.strip())
            configured = os.environ.get("TERRA_NOTO_FONT_DIR")
            args = [str(binary), "fonts", "--font-path", str(FONTS_DIR)]
            if configured:
                args.extend(["--font-path", configured])
            font_result = subprocess.run(args, capture_output=True, text=True, timeout=15, encoding="utf-8")
            from .i18n import TYPST_LANG_CONFIG
            for lang in languages:
                name = TYPST_LANG_CONFIG[lang]["cjk_font"]
                add(f"PDF/cover font {lang}", font_result.returncode == 0 and name in font_result.stdout, name)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            add("Typst", False, exc)
    if "epub" in formats:
        add("fonttools", importlib.util.find_spec("fontTools") is not None)
        add("EPUB stylesheet", STYLE_TEMPLATE_PATH.is_file(), STYLE_TEMPLATE_PATH)
        for name in ("EBGaramond-Regular.ttf", "EBGaramond-SemiBold.ttf", "EBGaramond-Italic.ttf"):
            add(name, (FONTS_DIR / name).is_file())
        for lang in languages:
            if lang == "en":
                continue
            for weight in ("Regular", "Bold"):
                try:
                    font, _ = _noto_font(lang, weight)
                    add(f"EPUB font {lang} {weight}", True, font)
                except (OSError, ValueError) as exc:
                    add(f"EPUB font {lang} {weight}", False, exc)
    return checks
