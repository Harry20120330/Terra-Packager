"""Five-language (zh, tw, en, ja, ko) localization, font mapping, and metadata helpers."""

from __future__ import annotations
from typing import Dict, List, Optional

LANGUAGES: List[str] = ["zh", "tw", "en", "ja", "ko"]

LANGUAGE_NAMES: Dict[str, str] = {
    "zh": "简体中文",
    "tw": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}

LANGUAGE_SHORT_NAMES: Dict[str, str] = {
    "zh": "简中",
    "tw": "繁中",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}

EPUB_LANG_TAGS: Dict[str, str] = {
    "zh": "zh-Hans",
    "tw": "zh-Hant",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
}

TYPST_LANG_CONFIG: Dict[str, Dict[str, str]] = {
    "zh": {"lang": "zh", "region": "cn", "cjk_font": "Noto Serif CJK SC"},
    "tw": {"lang": "zh", "region": "tw", "cjk_font": "Noto Serif CJK TC"},
    "en": {"lang": "en", "region": "us", "cjk_font": "Noto Serif CJK SC"},
    "ja": {"lang": "ja", "region": "jp", "cjk_font": "Noto Serif CJK JP"},
    "ko": {"lang": "ko", "region": "kr", "cjk_font": "Noto Serif CJK KR"},
}

# TTC indices inside /usr/share/fonts/opentype/noto/NotoSerifCJK-{Regular,Bold}.ttc
NOTO_TTC_INDEX: Dict[str, int] = {
    "ja": 0,
    "kr": 1,
    "ko": 1,
    "zh": 2,
    "tw": 3,
}

DEFAULT_NICKNAMES: Dict[str, str] = {
    "zh": "博士",
    "tw": "博士",
    "en": "Doctor",
    "ja": "ドクター",
    "ko": "박사",
}

UI_STRINGS: Dict[str, Dict[str, str]] = {
    "zh": {
        "cover_sub": "剧 情 文 库",
        "toc_heading": "目录 / Contents",
        "story_heading": "正文 / Story",
        "cover_nav_start": "开始阅读 / Start reading",
        "cover_nav_toc": "目录 / Contents",
        "cover_landmark": "封面 / Cover",
        "branch_fmt": "分支 / Branch {n}",
        "shared_cont": "共同接续 / Shared continuation",
        "cover_rights": "非官方整理·游戏文本权利归原权利人所有",
        "opf_rights": "非官方整理；游戏文本权利归原权利人。",
        "txt_rights": "游戏剧情文本、角色及相关内容的权利归原权利人所有。",
        "colon": "：",
    },
    "tw": {
        "cover_sub": "劇 情 文 庫",
        "toc_heading": "目錄 / Contents",
        "story_heading": "正文 / Story",
        "cover_nav_start": "開始閱讀 / Start reading",
        "cover_nav_toc": "目錄 / Contents",
        "cover_landmark": "封面 / Cover",
        "branch_fmt": "分支 / Branch {n}",
        "shared_cont": "共同接續 / Shared continuation",
        "cover_rights": "非官方整理·遊戲文本權利歸原權利人所有",
        "opf_rights": "非官方整理；遊戲文本權利歸原權利人。",
        "txt_rights": "遊戲劇情文本、角色及相關內容的權利歸原權利人所有。",
        "colon": "：",
    },
    "en": {
        "cover_sub": "S T O R Y   A R C H I V E",
        "toc_heading": "Contents",
        "story_heading": "Story",
        "cover_nav_start": "Start reading",
        "cover_nav_toc": "Contents",
        "cover_landmark": "Cover",
        "branch_fmt": "Branch {n}",
        "shared_cont": "Shared continuation",
        "cover_rights": "Unofficial archive · Game text belongs to original rightsholders",
        "opf_rights": "Unofficial archive; game text belongs to original rightsholders.",
        "txt_rights": "All rights to game story text, characters, and related content belong to their respective owners.",
        "colon": ": ",
    },
    "ja": {
        "cover_sub": "ス ト ー リ ー 文 庫",
        "toc_heading": "目次 / Contents",
        "story_heading": "本文 / Story",
        "cover_nav_start": "読み始める / Start reading",
        "cover_nav_toc": "目次 / Contents",
        "cover_landmark": "表紙 / Cover",
        "branch_fmt": "分岐 / Branch {n}",
        "shared_cont": "共通ルート / Shared continuation",
        "cover_rights": "非公式アーカイブ・ゲームテキストの権利は原権利者に帰属します",
        "opf_rights": "非公式整理；ゲームテキストの権利は原権利者に帰属します。",
        "txt_rights": "ゲームのストーリーテキスト、キャラクターおよび関連コンテンツの権利は原権利者に帰属します。",
        "colon": "：",
    },
    "ko": {
        "cover_sub": "스 토 리   문 고",
        "toc_heading": "목차 / Contents",
        "story_heading": "본문 / Story",
        "cover_nav_start": "읽기 시작 / Start reading",
        "cover_nav_toc": "목차 / Contents",
        "cover_landmark": "표지 / Cover",
        "branch_fmt": "분기 / Branch {n}",
        "shared_cont": "공통 이어짐 / Shared continuation",
        "cover_rights": "비공식 정리 · 게임 텍스트의 권리는 원저작권자 소유입니다",
        "opf_rights": "비공식 정리; 게임 텍스트의 권리는 원저작권자에게 있습니다.",
        "txt_rights": "게임 스토리 텍스트, 캐릭터 및 관련 콘텐츠의 권리는 원저작권자에게 귀속됩니다.",
        "colon": ": ",
    },
}

STAGE_PHASE_MAP: Dict[str, Dict[str, str]] = {
    "行动前": {
        "zh": "行动前",
        "tw": "行動前",
        "en": "Before Operation",
        "ja": "戦闘前",
        "ko": "작전 전",
    },
    "行动后": {
        "zh": "行动后",
        "tw": "行動後",
        "en": "After Operation",
        "ja": "戦闘後",
        "ko": "작전 후",
    },
    "幕间": {
        "zh": "幕间",
        "tw": "幕間",
        "en": "Interlude",
        "ja": "幕間",
        "ko": "막간",
    },
}


def localize_stage_tag(raw_tag: str, lang: str) -> str:
    """Localize stage tag such as '幕间' or '0-1 · 行动前' into target language."""
    if not raw_tag or lang == "zh":
        return raw_tag or ""
    result = raw_tag
    for zh_key, mapping in STAGE_PHASE_MAP.items():
        if zh_key in result:
            result = result.replace(zh_key, mapping.get(lang, zh_key))
    return result


def get_edition_badge(primary_lang: str, secondary_lang: Optional[str] = None) -> str:
    p = LANGUAGE_SHORT_NAMES.get(primary_lang, primary_lang)
    if secondary_lang and secondary_lang != primary_lang:
        s = LANGUAGE_SHORT_NAMES.get(secondary_lang, secondary_lang)
        return f"{p} / {s}"
    return p


def apply_nickname(text: str, lang: str, custom_nickname: Optional[str] = None) -> str:
    if not text:
        return ""
    default_nick = DEFAULT_NICKNAMES.get(lang, "博士")
    target_nick = (custom_nickname or "").strip() or default_nick
    return text.replace("{@nickname}", target_nick)
