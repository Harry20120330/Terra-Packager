"""Collect AVG stories, handbook archives and module narratives for publication.

Reference tables use explicit text fields. Unlock IDs, resources, costs and other
gameplay metadata are never recursively flattened into the publication body.
"""

from __future__ import annotations

import hashlib
import html
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .build_diagnostics import BuildDiagnostics
from .dag_linearizer import LinearBlock, LinearSection
from .i18n import LANGUAGES, apply_nickname
from .repo_provider import ExternalRepoProvider

CONTENT_TYPES: Tuple[str, ...] = (
    "mainline", "sidestory", "ministory", "operator-profile", "operator-record", "operator-module",
)

CONTENT_LABELS: Dict[str, Dict[str, str]] = {
    "mainline": {
        "zh": "主线剧情", "tw": "主線劇情", "en": "Main Story", "ja": "メインストーリー", "ko": "메인 스토리",
    },
    "sidestory": {
        "zh": "插曲与支线故事", "tw": "插曲與支線故事", "en": "Side Stories", "ja": "サイドストーリー", "ko": "사이드 스토리",
    },
    "ministory": {
        "zh": "故事集", "tw": "故事集", "en": "Vignettes", "ja": "幕間逸話", "ko": "그림자 속 이야기",
    },
    "operator-profile": {
        "zh": "干员档案", "tw": "幹員檔案", "en": "Operator Files", "ja": "オペレーター情報", "ko": "오퍼레이터 정보",
    },
    "operator-record": {
        "zh": "干员密录", "tw": "幹員密錄", "en": "Operator Records", "ja": "オペレーター秘録", "ko": "오퍼레이터 레코드",
    },
    "operator-module": {
        "zh": "干员模组", "tw": "幹員模組", "en": "Operator Modules", "ja": "オペレーターのモジュール", "ko": "오퍼레이터 모듈",
    },
}

COLLECTION_TITLES: Dict[str, Dict[str, str]] = {
    content_type: {
        lang: label + {"zh": "合集", "tw": "合集", "en": " Collection", "ja": "集", "ko": " 모음"}[lang]
        for lang, label in labels.items()
    }
    for content_type, labels in CONTENT_LABELS.items()
}
COLLECTION_TITLES["all"] = {
    "zh": "泰拉文库全内容合集", "tw": "泰拉文庫全內容合集", "en": "Terra Library Complete Collection",
    "ja": "テラ文庫 全コンテンツ集", "ko": "테라 라이브러리 전체 콘텐츠 모음",
}
COLLECTION_TITLES["selected"] = {
    "zh": "泰拉文库选集", "tw": "泰拉文庫選集", "en": "Terra Library Selected Collection",
    "ja": "テラ文庫 セレクション", "ko": "테라 라이브러리 선집",
}

_ENTRY_TYPES = {
    "mainline": "MAINLINE", "sidestory": "ACTIVITY", "ministory": "MINI_ACTIVITY", "operator-record": "NONE",
}
_SOURCE_NAMES = {"zh": "Simplified Chinese", "tw": "Traditional Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"}
_MISSING_TEXT = {
    "zh": "[译文不可用；以下为 {source} 原文]",
    "tw": "[譯文不可用；以下為 {source} 原文]",
    "en": "[Translation unavailable; original: {source}]",
    "ja": "[翻訳未収録・原文: {source}]",
    "ko": "[번역 없음; 원문: {source}]",
}
_MODULE_LABELS = {
    "zh": {"story": "模组故事", "info": "模组信息", "phase": "精英阶段", "level": "等级", "trust": "信赖", "favor": "信赖值", "unlock": "解锁条件"},
    "tw": {"story": "模組故事", "info": "模組資訊", "phase": "精英階段", "level": "等級", "trust": "信賴", "favor": "信賴值", "unlock": "解鎖條件"},
    "en": {"story": "Module story", "info": "Module information", "phase": "Elite phase", "level": "Level", "trust": "Trust", "favor": "Trust points", "unlock": "Unlock requirements"},
    "ja": {"story": "モジュールストーリー", "info": "モジュール情報", "phase": "昇進段階", "level": "レベル", "trust": "信頼度", "favor": "信頼ポイント", "unlock": "解放条件"},
    "ko": {"story": "모듈 스토리", "info": "모듈 정보", "phase": "정예 단계", "level": "레벨", "trust": "신뢰도", "favor": "신뢰 포인트", "unlock": "해금 조건"},
}

# Known localized headings give archive sections identities even when a server
# omits an entire section. Unknown headings retain their original array position.
_PROFILE_GROUP_NAMES = {
    "basic": ("基础档案", "基礎檔案", "基礎情報", "Basic File", "Basic Info", "기본 정보"),
    "exam": ("综合体检测试", "綜合體檢測試", "能力測定", "Physical Exam", "Physical Examination", "종합검진"),
    "resume": ("客观履历", "客觀履歷", "個人履歴", "Profile", "인적 사항"),
    "medical": ("临床诊断分析", "臨床診斷分析", "健康診断", "Clinical Analysis", "임상 진단 분석"),
    "promotion": ("晋升记录", "晉升記錄", "昇進記録", "Promotion Record", "진급 기록"),
}
_PROFILE_GROUP_KEYS = {name.casefold(): key for key, names in _PROFILE_GROUP_NAMES.items() for name in names}
for _number, _han in enumerate("一二三四五六", start=1):
    for _title in (
        f"档案资料{_han}", f"檔案資料{_han}", f"第{_han}資料", f"Archive File {_number}",
        f"File {_number}", f"파일 자료 {_number}",
    ):
        _PROFILE_GROUP_KEYS[_title.casefold()] = f"archive_{_number}"

_BR_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
_RICH_TAG = re.compile(r"</?(?:color|size|b|i|u|sup|sub)(?:\s[^>]*|=[^>]*|)>|</?[@$][^>]*>|</>", re.IGNORECASE)
_RowMap = Dict[str, Tuple[str, str]]


def _clean_text(value: Any) -> str:
    """Clean game markup without consuming paragraph boundaries or numeric metadata."""
    if not isinstance(value, str):
        return ""
    text = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n").replace("\\n", "\n")
    text = _BR_TAG.sub("\n", text)
    return _RICH_TAG.sub("", text).strip()


def _first_text(record: Dict[str, Any], *keys: str) -> str:
    return next((text for key in keys if (text := _clean_text(record.get(key)))), "")


def _active_languages(active_langs: Sequence[str]) -> List[str]:
    unknown = set(active_langs) - set(LANGUAGES)
    if unknown:
        raise ValueError(f"Unsupported languages: {', '.join(sorted(unknown))}")
    return list(dict.fromkeys(["zh", *active_langs]))


def _stable_id(content_type: str, key: str) -> str:
    digest = hashlib.sha256(f"{content_type}:{key}".encode("utf-8")).hexdigest()[:20]
    return f"terra_{content_type.replace('-', '_')}_{digest}"


def _tables(provider: ExternalRepoProvider, path: str, active: Sequence[str], use_cache: bool) -> Dict[str, dict]:
    tables: Dict[str, dict] = {}
    for lang in active:
        table = provider.get_json_table(lang, path, use_cache=use_cache)
        if table:
            tables[lang] = table
    return tables


def _record_map(table: dict, wrapper: str, prefix: str) -> Dict[str, dict]:
    """Read the upstream wrapper, also accepting a direct map of the same records."""
    records = table.get(wrapper, table)
    if not isinstance(records, dict):
        raise ValueError(f"Expected an object at {wrapper}")
    result: Dict[str, dict] = {}
    for key, record in records.items():
        if not str(key).startswith(prefix):
            continue
        if not isinstance(record, dict):
            raise ValueError(f"Expected an object at {wrapper}/{key}")
        result[str(key)] = record
    return result


def _character_names(provider: ExternalRepoProvider, active: Sequence[str], use_cache: bool) -> Dict[str, Dict[str, str]]:
    key = tuple(sorted(active))
    if key in provider._character_names_cache:
        return provider._character_names_cache[key]
    result: Dict[str, Dict[str, str]] = {}
    for lang, table in _tables(provider, "excel/character_table.json", active, use_cache).items():
        chars = table.get("chars", table)
        if not isinstance(chars, dict):
            raise ValueError("Expected an object in character_table.json")
        for char_id, character in chars.items():
            if isinstance(character, dict):
                name = _first_text(character, "name", "charName", "appellation")
                if name:
                    result.setdefault(str(char_id), {})[lang] = name
    provider._character_names_cache[key] = result
    return result


def _reference_blocks(
    scene_id: str,
    rows_by_lang: Dict[str, _RowMap],
    active: Sequence[str],
    custom_nickname: Optional[str],
) -> List[LinearBlock]:
    """Align stable fields before splitting paragraphs; never compact empty rows."""
    keys = list(dict.fromkeys(key for rows in rows_by_lang.values() for key in rows))
    blocks: List[LinearBlock] = []
    for key in keys:
        available = {lang: rows[key] for lang, rows in rows_by_lang.items() if key in rows and rows[key][1]}
        if not available:
            continue
        source = "zh" if "zh" in available else next(iter(available))
        paragraphs: Dict[str, List[str]] = {}
        labels: Dict[str, str] = {}
        for lang in active:
            row = available.get(lang)
            missing = row is None
            label, text = row or available[source]
            if missing:
                localized_rows = rows_by_lang.get(lang, {})
                existing_label = localized_rows.get(key, localized_rows.get(key.rsplit("/", 1)[0], ("", "")))[0]
                label = existing_label or label
            labels[lang] = apply_nickname(label, lang, custom_nickname)
            # One block per line keeps handbook lists and narrative paragraphs in
            # all formats, including XHTML where literal newlines would collapse.
            parts = [part.strip() for part in text.split("\n") if part.strip()]
            parts = [apply_nickname(part, lang if not missing else source, custom_nickname) for part in parts]
            if missing and parts:
                parts[0] = _MISSING_TEXT[lang].format(source=_SOURCE_NAMES[source]) + " " + parts[0]
            paragraphs[lang] = parts
        for index in range(max(map(len, paragraphs.values()), default=0)):
            texts = {lang: parts[index] for lang, parts in paragraphs.items() if index < len(parts)}
            blocks.append(LinearBlock(
                kind="utterance",
                line_id=_stable_id("reference_line", f"{scene_id}:{key}:{index}"),
                speakers=labels if index == 0 else {},
                texts=texts,
            ))
    return blocks


def _profile_rows(record: dict) -> _RowMap:
    rows: _RowMap = {}
    groups = record.get("storyTextAudio", [])
    if not isinstance(groups, list):
        raise ValueError("Expected handbook storyTextAudio to be a list")

    def visit(items: list, parent: str = "") -> None:
        for index, group in enumerate(items):
            if not isinstance(group, dict):
                raise ValueError("Expected a handbook archive group to be an object")
            label = _first_text(group, "storyTitle", "title")
            stable_key = _first_text(group, "storyId", "storyID", "storyCode")
            group_key = parent + (stable_key or _PROFILE_GROUP_KEYS.get(label.casefold(), f"group_{index}"))
            if group_key in rows:
                group_key += f"_{index}"
            stories = group.get("stories", [])
            if not isinstance(stories, list):
                raise ValueError(f"Expected handbook stories to be a list: {label}")
            # Older exports wrap named archive groups in one anonymous group.
            nested = [child for child in stories if isinstance(child, dict) and isinstance(child.get("stories"), list)]
            if nested:
                visit(stories, parent=group_key + "/")
                continue
            rows[group_key] = (label, "")
            seen_texts = set()
            for story_index, story in enumerate(stories):
                if not isinstance(story, dict):
                    raise ValueError(f"Expected a handbook story to be an object: {label}")
                text = _first_text(story, "storyText", "story")
                fields = {key.casefold(): value for key, value in story.items()}
                identity = _first_text(story, "storyId", "storyID", "storyCode")
                if not identity and "unlocktype" in fields and "unlockparam" in fields:
                    # Metadata is useful as an alignment identity, never as prose.
                    identity = f"{fields['unlocktype']}:{fields['unlockparam']}"
                row_key = group_key + "/" + (identity or f"story_{story_index}")
                if row_key in rows:
                    row_key += f"_{story_index}"
                if text not in seen_texts:
                    rows[row_key] = (label, text)
                    if text:
                        seen_texts.add(text)
            if not seen_texts:
                direct_text = _first_text(group, "storyText", "story")
                if direct_text:
                    rows[group_key] = (label, direct_text)

    visit(groups)
    return rows


def _profile_sections(
    provider: ExternalRepoProvider,
    active: Sequence[str],
    use_cache: bool,
    custom_nickname: Optional[str],
    report: Callable[[str, int], None],
) -> List[LinearSection]:
    records = {
        lang: _record_map(table, "handbookDict", "char_")
        for lang, table in _tables(provider, "excel/handbook_info_table.json", active, use_cache).items()
    }
    names = _character_names(provider, active, use_cache)
    identifiers = list(dict.fromkeys(key for table in records.values() for key in table))
    sections: List[LinearSection] = []
    for index, char_id in enumerate(identifiers, start=1):
        report(f"Collecting operator profile ({index}/{len(identifiers)}): {char_id}", int(100 * index / len(identifiers)))
        rows_by_lang = {lang: _profile_rows(table[char_id]) for lang, table in records.items() if char_id in table}
        scene_id = _stable_id("operator-profile", char_id)
        blocks = _reference_blocks(scene_id, rows_by_lang, active, custom_nickname)
        if not blocks:
            continue
        localized_names = dict(names.get(char_id, {}))
        for lang, table in records.items():
            name = _first_text(table.get(char_id, {}), "name", "charName")
            if name:
                localized_names[lang] = name
        fallback = localized_names.get("zh") or next(iter(localized_names.values()), char_id)
        titles = {lang: f"{localized_names.get(lang) or fallback} · {CONTENT_LABELS['operator-profile'][lang]}" for lang in LANGUAGES}
        sections.append(LinearSection(scene_id=scene_id, raw_tag="", titles=titles, blocks=blocks))
    return sections


def _module_story(record: dict) -> str:
    # uniEquipDesc is the narrative printed in the game's module detail screen.
    text = _first_text(record, "uniEquipDesc", "uniEquipStory", "storyText", "story", "description")
    if text:
        return text
    # Some exports use the same named text containers as the handbook. Reuse
    # their explicit storyText extraction instead of flattening arbitrary data.
    rows = _profile_rows(record)
    return "\n\n".join(dict.fromkeys(body for _, body in rows.values() if body))


def _module_records(table: dict) -> Dict[str, dict]:
    for wrapper in ("equipDict", "uniEquipDict", "uniEquipList"):
        if wrapper not in table:
            continue
        entries = table[wrapper]
        if isinstance(entries, dict):
            if any(not isinstance(record, dict) for record in entries.values()):
                raise ValueError(f"Expected module objects in {wrapper}")
            return {str(key): record for key, record in entries.items()}
        if isinstance(entries, list):
            records: Dict[str, dict] = {}
            for record in entries:
                if not isinstance(record, dict):
                    raise ValueError(f"Expected module objects in {wrapper}")
                module_id = _first_text(record, "uniEquipId", "id")
                if not module_id or module_id in records:
                    raise ValueError(f"Missing or duplicate module ID in {wrapper}: {module_id!r}")
                records[module_id] = record
            return records
        raise ValueError(f"Expected a module map or list at {wrapper}")
    return _record_map(table, "equipDict", "uniequip_")


def _module_rows(record: dict, lang: str) -> _RowMap:
    labels = _MODULE_LABELS[lang]
    rows: _RowMap = {"story": (labels["story"], _module_story(record))}
    info = _first_text(record, "uniEquipInfo", "info")
    if info and info != rows["story"][1]:
        rows["info"] = (labels["info"], info)
    unlock = _first_text(record, "unlockCondition", "unlockDescription")
    if unlock:
        rows["unlock"] = (labels["unlock"], unlock)
    for field, label_key in (
        ("unlockEvolvePhase", "phase"), ("unlockLevel", "level"),
        ("unlockTrust", "trust"), ("unlockFavPoint", "favor"), ("unlockFavorPoint", "favor"),
    ):
        value = record.get(field)
        if field == "unlockEvolvePhase" and isinstance(value, str):
            match = re.fullmatch(r"PHASE_(\d+)", value)
            value = int(match.group(1)) if match else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            rows[field] = (labels[label_key], str(value))
    return rows


def _module_sections(
    provider: ExternalRepoProvider,
    active: Sequence[str],
    use_cache: bool,
    custom_nickname: Optional[str],
    report: Callable[[str, int], None],
) -> List[LinearSection]:
    records = {
        lang: _module_records(table)
        for lang, table in _tables(provider, "excel/uniequip_table.json", active, use_cache).items()
    }
    names = _character_names(provider, active, use_cache)
    identifiers = list(dict.fromkeys(key for table in records.values() for key in table))
    sections: List[LinearSection] = []
    for index, module_id in enumerate(identifiers, start=1):
        record_by_lang = {lang: table[module_id] for lang, table in records.items() if module_id in table}
        source = record_by_lang.get("zh") or next(iter(record_by_lang.values()))
        # Initial/default equipment is not a module narrative, and usually has
        # a repeated class description. It must not become a spurious book.
        equip_type = str(source.get("type") or source.get("equipType") or "").upper()
        if equip_type in {"INITIAL", "DEFAULT"} or module_id.startswith("uniequip_001_"):
            continue
        if not any(_module_story(record) for record in record_by_lang.values()):
            continue
        report(f"Collecting operator module ({index}/{len(identifiers)}): {module_id}", int(100 * index / len(identifiers)))
        scene_id = _stable_id("operator-module", module_id)
        rows = {lang: _module_rows(record, lang) for lang, record in record_by_lang.items()}
        blocks = _reference_blocks(scene_id, rows, active, custom_nickname)
        char_id = _first_text(source, "charId", "charID")
        character_names = names.get(char_id, {})
        module_names = {lang: _first_text(record, "uniEquipName", "moduleName", "name") for lang, record in record_by_lang.items()}
        fallback_name = module_names.get("zh") or next((name for name in module_names.values() if name), module_id)
        fallback_char = character_names.get("zh") or next(iter(character_names.values()), char_id)
        titles = {}
        for lang in LANGUAGES:
            character = character_names.get(lang) or fallback_char
            name = module_names.get(lang) or fallback_name
            titles[lang] = f"{character} · {name}" if character else name
        sections.append(LinearSection(scene_id=scene_id, raw_tag="", titles=titles, blocks=blocks))
    return sections


def _rename_scene(section: LinearSection, content_type: str, group_id: str) -> None:
    unique_id = _stable_id(content_type, f"{group_id}:{section.scene_id}")
    section.scene_id = unique_id
    for index, block in enumerate(section.blocks):
        block.line_id = f"{unique_id}_line_{index}"
        block.options = [
            {**option, "id": f"{unique_id}_line_{index}_option_{option_index}"}
            for option_index, option in enumerate(block.options)
        ]


def collect_type_sections(
    provider: ExternalRepoProvider,
    content_type: str,
    active_langs: Sequence[str],
    use_cache: bool = True,
    custom_nickname: Optional[str] = None,
    volumes: Optional[List[dict]] = None,
    on_progress: Optional[Callable[[str, int], None]] = None,
    diagnostics: Optional[BuildDiagnostics] = None,
) -> Tuple[Dict[str, str], List[LinearSection]]:
    """Collect a category; optional preselected volumes restrict the four AVG types.

    Story categories contain level-1 volume dividers and level-2 AVG scenes.
    Operator archives and module narratives use one level-1 section per entry.
    Missing reference translations are explicitly marked when a source fallback
    is shown. Numeric gameplay metadata is only emitted as labeled requirements.
    """
    if content_type not in CONTENT_TYPES:
        raise ValueError(f"Unsupported content type: {content_type!r}; expected one of {', '.join(CONTENT_TYPES)}")
    active = _active_languages(active_langs)
    diagnostics = diagnostics if diagnostics is not None else BuildDiagnostics(on_progress=on_progress)

    def report(message: str, pct: int) -> None:
        if on_progress:
            on_progress(message, pct)

    report(f"Reading {CONTENT_LABELS[content_type].get('en', content_type)}...", 0)
    if content_type in _ENTRY_TYPES:
        catalog = volumes if volumes is not None else provider.list_volumes(active_langs=active, use_cache=use_cache)
        selected = [volume for volume in catalog if volume.get("entryType") == _ENTRY_TYPES[content_type]]
        provider.prefetch(((lang, f"story/{meta['storyTxt']}.txt") for volume in selected
                           for meta in volume.get("scenesMeta", []) for lang in active_langs), use_cache)
        total = sum(len(volume.get("scenesMeta") or []) for volume in selected)
        completed = 0
        sections: List[LinearSection] = []
        for volume in selected:
            scenes_meta = volume.get("scenesMeta") or []
            if not scenes_meta:
                continue
            volume_sections: List[LinearSection] = []
            divider = LinearSection(
                scene_id=_stable_id("volume", str(volume["groupId"])),
                raw_tag=volume.get("volumeNumber") or "",
                titles=dict(volume["titles"]),
                blocks=[],
                heading_level=1,
                is_divider=True,
            )
            for meta in scenes_meta:
                completed += 1
                report(
                    f"Compiling {CONTENT_LABELS[content_type].get('en', content_type)} "
                    f"({completed}/{total}): {meta['storyTxt']}",
                    int(100 * completed / total),
                )
                section = diagnostics.compile_scene(
                    provider, meta, active_langs, use_cache=use_cache, custom_nickname=custom_nickname,
                )
                if section is None:
                    continue
                _rename_scene(section, content_type, str(volume["groupId"]))
                section.heading_level = 2
                volume_sections.append(section)
            if volume_sections:
                sections.extend([divider, *volume_sections])
    elif content_type == "operator-profile":
        sections = _profile_sections(provider, active, use_cache, custom_nickname, report)
    else:
        sections = _module_sections(provider, active, use_cache, custom_nickname, report)
    return (dict(COLLECTION_TITLES[content_type]) if sections else {}, sections)
