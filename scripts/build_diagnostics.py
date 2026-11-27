"""Report missing story sources consistently across all publication modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from .avg_compiler import compile_scene_from_repo
from .dag_linearizer import LinearSection, linearize_scene
from .i18n import LANGUAGES
from .repo_provider import ExternalRepoProvider
from .runtime import measured


@dataclass
class BuildDiagnostics:
    missing_scenes: List[str] = field(default_factory=list)
    missing_categories: List[str] = field(default_factory=list)
    partial_scenes: Dict[str, List[str]] = field(default_factory=dict)
    fallback_scenes: List[str] = field(default_factory=list)
    media_scenes: List[str] = field(default_factory=list)
    source_order_scenes: List[str] = field(default_factory=list)
    on_progress: Optional[Callable[[str, int], None]] = None
    skip_missing: bool = False

    def _report(self, message: str) -> None:
        if self.on_progress is not None:
            self.on_progress(message, 0)

    @property
    def has_omissions(self) -> bool:
        """A partial translation is retained content, not an omitted scene."""
        return bool(self.missing_scenes or self.missing_categories)

    def compile_scene(
        self,
        provider: ExternalRepoProvider,
        scene_meta: dict,
        active_langs: Sequence[str],
        use_cache: bool = True,
        custom_nickname: Optional[str] = None,
    ) -> Optional[LinearSection]:
        requested = list(dict.fromkeys(active_langs))
        if not requested or any(lang not in LANGUAGES for lang in requested):
            raise ValueError(f"Unsupported or empty requested languages: {requested}")
        source = str(scene_meta.get("storyTxt") or scene_meta.get("id") or "unknown scene")
        try:
            with measured("story_compile"):
                scene = compile_scene_from_repo(provider, scene_meta, requested, use_cache=use_cache)
                section = linearize_scene(scene, meta=scene_meta, custom_nickname=custom_nickname)
            available = set(scene.get("availableLanguages", []))
            # File presence alone is insufficient: a locale can contain only
            # visual directives or unlabeled decisions. Require actual source
            # text as well as text surviving compilation and linearization.
            source_text = set(scene.get("sourceTextLanguages", available))
            if not source_text and set(requested) <= set(scene.get("mediaOnlyLanguages", [])):
                if source not in self.media_scenes:
                    self.media_scenes.append(source)
                self._report(f"Skipping video-only scene: {source} (no printable story text).")
                return None
            readable = {
                lang for lang in requested
                if lang in available and lang in source_text and any(
                    (block.kind == "utterance" and (block.texts.get(lang) or "").strip())
                    or (block.kind == "choices" and any(
                        (option.get("texts", {}).get(lang) or "").strip()
                        for option in block.options
                    ))
                    for block in section.blocks
                )
            }
            if not readable:
                raise FileNotFoundError(
                    f"No readable story text for requested languages {'/'.join(requested)}: {source}"
                )
        except FileNotFoundError as exc:
            if not self.skip_missing:
                raise
            if source not in self.missing_scenes:
                self.missing_scenes.append(source)
            self._report(f"Skipping missing script: {source} ({exc})")
            return None

        missing = [lang for lang in requested if lang not in readable]
        for lang, warning in scene.get("structureWarnings", {}).items():
            if source not in self.source_order_scenes:
                self.source_order_scenes.append(source)
            self._report(f"Warning: {warning}; {lang} prose and choices are preserved in source order.")
        if section.alignment_status == "separate":
            if source not in self.fallback_scenes:
                self.fallback_scenes.append(source)
            self._report(f"Warning: {source}: structures differ; complete language versions are shown separately.")
        if missing:
            self.partial_scenes[source] = missing
            self._report(
                f"Warning: {source} is missing {'/'.join(missing)}; "
                "the scene will include only available languages."
            )
        return section

    def empty_category(self, kind: str, label: str) -> None:
        if not self.skip_missing:
            raise ValueError(
                f"No content found for requested content type: {kind} ({label}). "
                "Check the local data contains all six content types and the requested languages."
            )
        if kind not in self.missing_categories:
            self.missing_categories.append(kind)
        self._report(f"Skipping missing content type: {label} ({kind}); no readable text found.")

    def summary(self) -> str:
        if not (self.has_omissions or self.partial_scenes or self.fallback_scenes or self.media_scenes or self.source_order_scenes):
            return ""
        return (
            f"Build summary: {len(self.missing_scenes)} missing scene(s), "
            f"{len(self.missing_categories)} missing content type(s), "
            f"{len(self.partial_scenes)} partially translated scene(s), "
            f"{len(self.fallback_scenes)} separately preserved bilingual scene(s), "
            f"{len(self.media_scenes)} video-only scene(s) skipped, "
            f"{len(self.source_order_scenes)} scene(s) preserved in source order."
        )
