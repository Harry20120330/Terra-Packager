"""External Arknights Gamedata repository connector (Remote GitHub Raw & Local Clones)."""

from __future__ import annotations
import json
import os
import re
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .i18n import LANGUAGES
from .runtime import atomic_write, cache_root, measured

# Server folder mappings for supported upstream repository conventions
ARKNIGHTS_ASSETS_MAP: Dict[str, str] = {
    "zh": "cn",
    "tw": "tw",
    "en": "en",
    "ja": "jp",
    "ko": "kr",
}

KENGXXIAO_SUBDIR_MAP: Dict[str, str] = {
    "zh": "zh_CN",
    "tw": "zh_TW",
    "en": "en_US",
    "ja": "ja_JP",
    "ko": "ko_KR",
}

DEFAULT_ARKNIGHTS_ASSETS_BASE = "https://raw.githubusercontent.com/ArknightsAssets/ArknightsGamedata/master"
DEFAULT_KENGXXIAO_CN_BASE = "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master"
DEFAULT_KENGXXIAO_YOSTAR_BASE = "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData_YoStar/main"

CATEGORY_LABELS: Dict[str, str] = {
    "MAINLINE": "主线剧情",
    "ACTIVITY": "插曲与支线故事",
    "MINI_ACTIVITY": "故事集",
    "NONE": "干员密录",
}


class ExternalRepoProvider:
    """
    Unified reader for external Arknights resource repositories:
      - source='arknights-assets' : ArknightsAssets/ArknightsGamedata (5 languages in one repo)
      - source='kengxxiao'        : Kengxxiao/ArknightsGameData (CN) + ArknightsGameData_YoStar (TW/EN/JP/KR)
      - repo_dir=<Path>           : Local git clone of either repo layout (100% offline)
      - repo_url=<str>            : Custom mirror base URL following ArknightsAssets layout
    """

    def __init__(
        self,
        source: str = "arknights-assets",
        repo_dir: Optional[Path] = None,
        yostar_dir: Optional[Path] = None,
        repo_url: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        timeout: int = 30,
        jobs: int = 4,
        measurements=None,
    ) -> None:
        self.source = source
        self.repo_dir = Path(repo_dir).resolve() if repo_dir else None
        self.yostar_dir = Path(yostar_dir).resolve() if yostar_dir else None
        self.repo_url = repo_url.rstrip("/") if repo_url else DEFAULT_ARKNIGHTS_ASSETS_BASE
        self.cache_dir = (
            Path(cache_dir).resolve()
            if cache_dir
            else cache_root()
        )
        self.timeout = timeout
        if not 1 <= jobs <= 8:
            raise ValueError("--jobs must be between 1 and 8")
        self.jobs = jobs
        self.measurements = measurements
        self._texts = {}
        self._locks = {}
        self._lock = threading.Lock()
        self._catalogs = {}
        self._volume_indexes = {}
        self._character_names_cache = {}
        self._review_tables: Dict[str, Dict[str, Any]] = {}
        self._json_tables: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def _local_gamedata_root(self, lang: str) -> Optional[Path]:
        if not self.repo_dir:
            return None
        # 1. ArknightsAssets layout: <repo_dir>/{cn,tw,en,jp,kr}/gamedata
        aa_sub = self.repo_dir / ARKNIGHTS_ASSETS_MAP[lang] / "gamedata"
        if aa_sub.is_dir():
            return aa_sub
        # 2. Kengxxiao layout in single or split directories
        kx_code = KENGXXIAO_SUBDIR_MAP[lang]
        for base in [self.repo_dir, self.yostar_dir]:
            if base and (base / kx_code / "gamedata").is_dir():
                return base / kx_code / "gamedata"
        # 3. Single-server bare gamedata directory (assume matches requested primary/zh)
        if lang == "zh" and (self.repo_dir / "gamedata").is_dir():
            return self.repo_dir / "gamedata"
        if lang == "zh" and (self.repo_dir / "excel").is_dir():
            return self.repo_dir
        return None

    def _remote_urls_for(self, lang: str, rel_gamedata_path: str) -> List[str]:
        """Return prioritized remote URLs (primary source + automatic mirror fallback)."""
        aa_url = f"{self.repo_url}/{ARKNIGHTS_ASSETS_MAP[lang]}/gamedata/{rel_gamedata_path}"
        kx_base = DEFAULT_KENGXXIAO_CN_BASE if lang == "zh" else DEFAULT_KENGXXIAO_YOSTAR_BASE
        kx_url = f"{kx_base}/{KENGXXIAO_SUBDIR_MAP[lang]}/gamedata/{rel_gamedata_path}"

        if self.source == "kengxxiao":
            return [kx_url, aa_url]
        return [aa_url, kx_url]

    def fetch_text(self, lang: str, rel_gamedata_path: str, use_cache: bool = True) -> Optional[str]:
        """Read a gamedata file (JSON or AVG .txt) from local repo, disk cache, or remote GitHub."""
        if lang not in LANGUAGES:
            raise ValueError(f"Unsupported language: {lang}")
        relative = Path(rel_gamedata_path)
        if relative.is_absolute() or relative.drive or rel_gamedata_path.startswith("/") or ".." in relative.parts or "\\" in rel_gamedata_path:
            raise ValueError("Resource paths must stay within gamedata")
        key = (lang, rel_gamedata_path)
        with self._lock:
            resource_lock = self._locks.setdefault(key, threading.Lock())
        with resource_lock:
            if key in self._texts:
                if self.measurements:
                    self.measurements.count("resource_memory_hits")
                return self._texts[key]
            with self.measurements.stage("resource_tasks") if self.measurements else nullcontext():
                text = self._fetch_text(lang, rel_gamedata_path, use_cache)
            self._texts[key] = text
            return text

    def prefetch(self, resources, use_cache=True):
        if self.repo_dir is not None:
            return
        requests = list(dict.fromkeys(resources))
        with self.measurements.stage("download_wall") if self.measurements else nullcontext():
            with ThreadPoolExecutor(max_workers=self.jobs) as executor:
                # Consume all futures in input order to surface failures deterministically.
                futures = [executor.submit(self.fetch_text, lang, path, use_cache) for lang, path in requests]
                for future in futures:
                    future.result()

    def _fetch_text(self, lang, rel_gamedata_path, use_cache):
        local_root = self._local_gamedata_root(lang)
        if self.repo_dir is not None:
            # A local repository is an offline source, including missing locales.
            if local_root is None:
                return None
            fpath = local_root / rel_gamedata_path
            if fpath.is_file():
                return fpath.read_text(encoding="utf-8-sig")
            return None

        config = json.dumps([self.source, self.repo_url], ensure_ascii=True)
        namespace = hashlib.sha256(config.encode()).hexdigest()[:20]
        urls = list(dict.fromkeys(self._remote_urls_for(lang, rel_gamedata_path)))
        errors = []
        for url in urls:
            url_key = hashlib.sha256(url.encode()).hexdigest()
            cache_file = self.cache_dir / "resources-v2" / namespace / f"{url_key}.json"
            if use_cache and cache_file.is_file():
                try:
                    cached = json.loads(cache_file.read_text(encoding="utf-8"))
                    if cached["url"] == url and isinstance(cached["text"], str):
                        if self.measurements:
                            self.measurements.count("resource_disk_hits")
                        return cached["text"]
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            for attempt in range(3):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "TerraPackager/1.0"})
                    if self.measurements:
                        self.measurements.count("network_requests")
                    with urllib.request.urlopen(req, timeout=self.timeout) as response:
                        text = response.read().decode("utf-8-sig")
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        break
                    retryable = exc.code == 429 or 500 <= exc.code < 600
                    if not retryable or attempt == 2:
                        errors.append(f"{url}: HTTP {exc.code}")
                        break
                    delay = 2 ** attempt
                    header = exc.headers.get("Retry-After") if exc.headers else None
                    if header:
                        try:
                            delay = float(header)
                        except ValueError:
                            try:
                                delay = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
                            except (ValueError, TypeError):
                                pass
                    time.sleep(min(30, max(0, delay)))
                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                    if attempt == 2:
                        errors.append(f"{url}: {exc}")
                    else:
                        time.sleep(2 ** attempt)
                else:
                    # A cache write failure is local I/O, never a reason to retry the network.
                    atomic_write(cache_file, json.dumps({"url": url, "text": text}, ensure_ascii=False).encode("utf-8"))
                    return text
        if errors:
            raise RuntimeError("Resource download failed; this is not a missing script:\n" + "\n".join(errors))
        return None

    def get_json_table(
        self,
        lang: str,
        rel_gamedata_path: str,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Read a JSON table, preserving missing-file semantics but surfacing corruption."""
        key = (lang, rel_gamedata_path)
        if key in self._json_tables:
            return self._json_tables[key]
        raw = self.fetch_text(lang, rel_gamedata_path, use_cache=use_cache)
        if raw is None:
            self._json_tables[key] = {}
            return {}
        try:
            parsed = json.loads(raw.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {lang}/{rel_gamedata_path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected a JSON object in {lang}/{rel_gamedata_path}")
        self._json_tables[key] = parsed
        return parsed

    def get_story_review_table(self, lang: str, use_cache: bool = True) -> Dict[str, Any]:
        parsed = self.get_json_table(lang, "excel/story_review_table.json", use_cache=use_cache)
        self._review_tables[lang] = parsed
        return parsed

    @staticmethod
    def _volume_sort_key(gid: str, group_obj: Dict[str, Any]) -> Tuple[int, int, str]:
        entry_type = group_obj.get("entryType") or "NONE"
        if entry_type == "MAINLINE":
            m = re.match(r"^main_(\d+)$", gid)
            chap_num = int(m.group(1)) if m else 999
            return (0, chap_num, gid)
        type_rank = {
            "ACTIVITY": 1,
            "MINI_ACTIVITY": 2,
            "NONE": 3,
        }.get(entry_type, 4)
        start_time = int(group_obj.get("startTime") or 0)
        return (type_rank, start_time if start_time > 0 else 9999999999, gid)

    def list_volumes(
        self,
        active_langs: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Build numbered volume catalog directly from upstream story_review_table.json."""
        langs_to_load = list(dict.fromkeys(["zh", *(active_langs or [])]))
        key = tuple(sorted(langs_to_load))
        if key in self._catalogs:
            return self._catalogs[key]
        with measured("catalog"):
            volumes = self._build_catalog(langs_to_load, use_cache)
        self._catalogs[key] = volumes
        index = {}
        for volume in volumes:
            aliases = [volume["volumeNumber"], volume["groupId"],
                       f"{volume['volumeNumber']}-{volume['titles']['zh']}", *volume["titles"].values()]
            for alias in aliases:
                index.setdefault(alias, volume)
        self._volume_indexes[key] = index
        if self.measurements:
            self.measurements.count("catalog_builds")
        return volumes

    def _build_catalog(self, langs_to_load, use_cache):
        tables = {l: self.get_story_review_table(l, use_cache=use_cache) for l in langs_to_load}
        cn_table = tables.get("zh") or next((t for t in tables.values() if t), {})
        localized_scenes = {lang: {gid: {u.get("storyTxt"): u.get("storyName")
                                      for u in group.get("infoUnlockDatas", [])}
                                  for gid, group in table.items()} for lang, table in tables.items()}

        sorted_gids = sorted(
            cn_table.keys(),
            key=lambda g: self._volume_sort_key(g, cn_table[g]),
        )

        volumes: List[Dict[str, Any]] = []
        vol_idx = 0
        for gid in sorted_gids:
            g_cn = cn_table[gid]
            unlocks_cn = [
                u for u in (g_cn.get("infoUnlockDatas") or [])
                if u.get("storyTxt")
            ]
            if not unlocks_cn:
                continue

            vol_idx += 1
            vol_num = f"{vol_idx:03d}"
            entry_type = g_cn.get("entryType") or "NONE"

            titles: Dict[str, str] = {}
            for lang in LANGUAGES:
                tbl = tables.get(lang)
                if tbl and gid in tbl and tbl[gid].get("name"):
                    titles[lang] = tbl[gid]["name"]
                else:
                    titles[lang] = g_cn.get("name") or gid

            scenes_meta: List[Dict[str, Any]] = []
            for seq_idx, u_cn in enumerate(unlocks_cn):
                story_txt = u_cn["storyTxt"]
                scene_id = "ak_" + story_txt.replace("/", "_")
                story_code = (u_cn.get("storyCode") or "").strip()
                avg_tag = (u_cn.get("avgTag") or "").strip()
                tag = f"{story_code} · {avg_tag}" if story_code and avg_tag else (story_code or avg_tag)

                scene_entry: Dict[str, Any] = {
                    "id": scene_id,
                    "storyTxt": story_txt,
                    "tag": tag,
                    "groupId": gid,
                    "sequencePosition": seq_idx,
                    "title_zh": u_cn.get("storyName") or scene_id,
                }
                for lang in LANGUAGES:
                    if lang == "zh":
                        continue
                    tbl = tables.get(lang)
                    localized_title = None
                    if tbl and gid in tbl:
                        localized_title = localized_scenes[lang][gid].get(story_txt)
                    scene_entry[f"title_{lang}"] = localized_title or scene_entry["title_zh"]

                scenes_meta.append(scene_entry)

            volumes.append({
                "volumeNumber": vol_num,
                "groupId": gid,
                "entryType": entry_type,
                "categoryTitle": CATEGORY_LABELS.get(entry_type, entry_type),
                "titles": titles,
                "sceneCount": len(scenes_meta),
                "scenesMeta": scenes_meta,
            })
        return volumes

    def resolve_volume(
        self,
        identifier: str,
        active_langs: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        vols = self.list_volumes(active_langs=active_langs, use_cache=use_cache)
        q = identifier.strip()
        key = tuple(sorted(set(["zh", *(active_langs or [])])))
        if q in self._volume_indexes[key]:
            return self._volume_indexes[key][q]
        # Fuzzy substring match fallback
        q_low = q.lower()
        for v in vols:
            if any(q_low in t.lower() for t in v["titles"].values()):
                return v
        raise KeyError(f"Volume not found in external repository: {identifier!r}")
