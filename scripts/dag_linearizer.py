"""Deterministic AVG story DAG linearizer with First Shared Continuation (LCA) detection."""

from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .i18n import LANGUAGES, LANGUAGE_NAMES, UI_STRINGS, apply_nickname


@dataclass
class LinearBlock:
    """One linearized unit inside a story section."""
    kind: str  # 'utterance' | 'choices' | 'branch_notice' | 'shared_notice'
    line_id: str = ""
    depth: int = 0
    speakers: Dict[str, str] = field(default_factory=dict)
    texts: Dict[str, str] = field(default_factory=dict)
    options: List[Dict[str, Any]] = field(default_factory=list)
    branch_index: int = 0


@dataclass
class LinearSection:
    scene_id: str
    raw_tag: str
    titles: Dict[str, str]
    blocks: List[LinearBlock]
    heading_level: int = 1
    is_divider: bool = False
    alignment_status: str = "aligned"


def _build_graph(scene: Dict[str, Any]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, Any]], List[int]]:
    nodes_by_id: Dict[int, Dict[str, Any]] = {}
    topo_order: List[int] = []
    for n in sorted(scene.get("nodes", []), key=lambda x: x.get("sourceIndex", 0)):
        nid = int(n["id"])
        nodes_by_id[nid] = n
        topo_order.append(nid)
    lines_by_id: Dict[str, Dict[str, Any]] = {ln["id"]: ln for ln in scene.get("lines", [])}
    return nodes_by_id, lines_by_id, topo_order


def _reachable_nodes(start_id: Optional[int], nodes_by_id: Dict[int, Dict[str, Any]], stop_id: Optional[int] = None) -> Set[int]:
    if start_id is None or start_id not in nodes_by_id:
        return set()
    visited: Set[int] = set()
    q: deque[int] = deque([start_id])
    while q:
        cur = q.popleft()
        if cur in visited:
            continue
        visited.add(cur)
        if stop_id is not None and cur == stop_id:
            continue
        node = nodes_by_id.get(cur)
        if not node:
            continue
        for edge in node.get("edges", []):
            tgt = edge.get("target")
            if tgt is not None and int(tgt) not in visited:
                q.append(int(tgt))
    return visited


def _find_join_node(
    targets: List[Optional[int]],
    nodes_by_id: Dict[int, Dict[str, Any]],
    source_idx_map: Dict[int, int],
    stop_id: Optional[int],
) -> Optional[int]:
    valid_targets = [int(t) for t in targets if t is not None and int(t) in nodes_by_id]
    if not valid_targets:
        return stop_id
    reach_sets = [_reachable_nodes(t, nodes_by_id, stop_id=stop_id) for t in valid_targets]
    common = set.intersection(*reach_sets) if reach_sets else set()
    if not common:
        return stop_id
    return min(common, key=lambda nid: source_idx_map.get(nid, 10**9))


def _node_has_visible_content(
    start_id: Optional[int],
    stop_id: Optional[int],
    nodes_by_id: Dict[int, Dict[str, Any]],
    lines_by_id: Dict[str, Dict[str, Any]],
) -> bool:
    if start_id is None or start_id == stop_id or start_id not in nodes_by_id:
        return False
    visited: Set[int] = set()
    q: deque[int] = deque([start_id])
    while q:
        cur = q.popleft()
        if cur == stop_id or cur in visited:
            continue
        visited.add(cur)
        node = nodes_by_id.get(cur)
        if not node:
            continue
        for eid in node.get("events", []):
            ln = lines_by_id.get(eid)
            if ln and ln.get("type") in ("dialogue", "narration", "choice", "screen"):
                return True
        for edge in node.get("edges", []):
            tgt = edge.get("target")
            if tgt is not None and int(tgt) != stop_id and int(tgt) not in visited:
                q.append(int(tgt))
    return False


def linearize_scene(
    scene: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    custom_nickname: Optional[str] = None,
) -> LinearSection:
    if scene.get("alignmentStatus") == "separate":
        notices = {
            "zh": "双语结构无法可靠对齐；以下分别保留各语言完整场景。",
            "tw": "雙語結構無法可靠對齊；以下分別保留各語言完整場景。",
            "en": "The scene structures cannot be aligned reliably. Complete language versions follow separately.",
            "ja": "構造を正確に対応付けできないため、各言語の全文を個別に掲載します。",
            "ko": "구조를 정확히 대응할 수 없어 각 언어의 전체 내용을 따로 수록합니다.",
        }
        blocks = [LinearBlock(kind="utterance", line_id=f"{scene['id']}_alignment",
                              texts={lang: notices[lang] for lang in scene["requestedLanguages"]})]
        for lang, localized_scene in scene["languageScenes"].items():
            blocks.append(LinearBlock(kind="utterance", line_id=f"{scene['id']}_{lang}_label",
                                      texts={lang: LANGUAGE_NAMES[lang]}))
            localized = linearize_scene(localized_scene, meta=meta, custom_nickname=custom_nickname)
            for index, block in enumerate(localized.blocks):
                if block.kind in ("branch_notice", "shared_notice"):
                    label = (UI_STRINGS[lang]["branch_fmt"].format(n=block.branch_index)
                             if block.kind == "branch_notice" else UI_STRINGS[lang]["shared_cont"])
                    block = LinearBlock(kind="utterance", line_id=f"{scene['id']}_{lang}_notice_{index}",
                                        depth=block.depth, texts={lang: label})
                blocks.append(block)
        source = meta or scene
        return LinearSection(scene_id=scene["id"], raw_tag=source.get("tag", ""),
                             titles={lang: source.get(f"title_{lang}") or source.get("title_zh") or scene["id"]
                                     for lang in LANGUAGES}, blocks=blocks, alignment_status="separate")
    nodes_by_id, lines_by_id, _ = _build_graph(scene)
    source_idx_map = {nid: n.get("sourceIndex", 0) for nid, n in nodes_by_id.items()}

    entry_id = scene.get("entryNodeId")
    if entry_id is None and scene.get("nodes"):
        entry_id = scene["nodes"][0]["id"]

    blocks: List[LinearBlock] = []

    def walk(start_id: Optional[int], stop_id: Optional[int], depth: int, visited_guard: Set[int]) -> None:
        cur = int(start_id) if start_id is not None else None
        while cur is not None and cur != stop_id and cur in nodes_by_id:
            if cur in visited_guard:
                break
            visited_guard.add(cur)
            node = nodes_by_id[cur]
            events = node.get("events", [])

            choice_line: Optional[Dict[str, Any]] = None
            for eid in events:
                ln = lines_by_id.get(eid)
                if not ln:
                    continue
                ltype = ln.get("type")
                if ltype == "choice":
                    choice_line = ln
                elif ltype in ("dialogue", "narration", "screen"):
                    texts = {
                        lang: apply_nickname(ln.get(lang) or "", lang, custom_nickname)
                        for lang in LANGUAGES
                    }
                    if any(texts.values()):
                        speakers = {
                            lang: apply_nickname(ln.get(f"spk_{lang}") or "", lang, custom_nickname)
                            for lang in LANGUAGES
                        }
                        blocks.append(
                            LinearBlock(
                                kind="utterance",
                                line_id=ln["id"],
                                depth=depth,
                                speakers=speakers,
                                texts=texts,
                            )
                        )

            if choice_line is not None:
                raw_opts = choice_line.get("options") or []
                opt_items: List[Dict[str, Any]] = []
                targets: List[Optional[int]] = []
                for idx, opt in enumerate(raw_opts, start=1):
                    tgt = opt.get("target")
                    if tgt is None and isinstance(opt.get("runtime"), dict):
                        tgt = opt["runtime"].get("target")
                    tgt_int = int(tgt) if tgt is not None else None
                    targets.append(tgt_int)
                    opt_texts = {
                        lang: apply_nickname(opt.get(lang) or "", lang, custom_nickname)
                        for lang in LANGUAGES
                    }
                    opt_items.append({
                        "index": idx,
                        "id": opt.get("id") or f"{choice_line['id']}-option-{idx}",
                        "target": tgt_int,
                        "texts": opt_texts,
                    })

                blocks.append(
                    LinearBlock(
                        kind="choices",
                        line_id=choice_line["id"],
                        depth=depth,
                        options=opt_items,
                    )
                )

                # Single option pass-through
                if len(opt_items) <= 1:
                    cur = targets[0] if targets else None
                    continue

                join_node = _find_join_node(targets, nodes_by_id, source_idx_map, stop_id)
                any_branch_content = any(
                    _node_has_visible_content(t, join_node, nodes_by_id, lines_by_id)
                    for t in targets
                )

                if not any_branch_content:
                    cur = join_node
                    continue

                next_depth = min(depth + 1, 3)
                for idx, t in enumerate(targets, start=1):
                    blocks.append(
                        LinearBlock(
                            kind="branch_notice",
                            depth=depth,
                            branch_index=idx,
                        )
                    )
                    branch_guard = set(visited_guard)
                    walk(t, join_node, next_depth, branch_guard)

                if join_node is not None and join_node != stop_id and _node_has_visible_content(
                    join_node, stop_id, nodes_by_id, lines_by_id
                ):
                    if depth == 0:
                        blocks.append(LinearBlock(kind="shared_notice", depth=depth))
                cur = join_node
                continue

            edges = node.get("edges") or []
            if not edges:
                break
            next_target = edges[0].get("target")
            cur = int(next_target) if next_target is not None else None

    walk(entry_id, None, 0, set())

    src_meta = meta or scene
    titles = {
        lang: src_meta.get(f"title_{lang}") or scene.get(f"title_{lang}") or src_meta.get("title_zh") or scene["id"]
        for lang in LANGUAGES
    }
    raw_tag = src_meta.get("tag") or scene.get("tag") or ""
    return LinearSection(
        scene_id=scene["id"],
        raw_tag=raw_tag,
        titles=titles,
        blocks=blocks,
    )
