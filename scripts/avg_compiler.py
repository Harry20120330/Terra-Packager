"""Raw Arknights AVG .txt script parser & 5-language parallel DAG compiler."""

from __future__ import annotations
import hashlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .i18n import LANGUAGES
from .repo_provider import ExternalRepoProvider

ATTR_RE = re.compile(r'([A-Za-z0-9_]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|([^\s,\]]+))')
RICH_TAG_RE = re.compile(
    r"</?(?:(?:color|i|b|u|size)(?=[\s=>/])[^>]*|[@$][^>\s]+[^>]*)>|</>",
    re.IGNORECASE,
)


def _clean_avg_text(raw: str, lang: str) -> str:
    if not raw:
        return ""
    txt = raw.replace("\\n", " ").replace('\\"', '"')
    txt = RICH_TAG_RE.sub("", txt)
    txt = txt.replace("</>", "")
    return txt.strip()


def _parse_attrs(attr_str: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in ATTR_RE.finditer(attr_str):
        key = m.group(1).lower()
        val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        out[key] = val or ""
    return out


def parse_raw_avg_tokens(raw_txt: str, lang: str) -> List[Dict[str, Any]]:
    """
    Parse one raw AVG .txt script into ordered structural/text tokens:
      - {'kind': 'utterance', 'speaker': str, 'text': str}
      - {'kind': 'decision', 'options': List[str], 'values': List[str]}
      - {'kind': 'predicate', 'refs': Optional[List[str]]}  # refs=None means bare [Predicate] rejoin
    """
    tokens: List[Dict[str, Any]] = []
    multiline_buf: List[str] = []
    multiline_spk: str = ""

    for raw_line in raw_txt.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        # 1. [name="Speaker"] Dialogue text
        m_name = re.match(r'^\[name\s*=\s*"([^"]*)"\s*\](.*)$', line, re.IGNORECASE)
        if m_name:
            spk = _clean_avg_text(m_name.group(1), lang)
            txt = _clean_avg_text(m_name.group(2), lang)
            if txt:
                tokens.append({"kind": "utterance", "speaker": spk, "text": txt})
            continue

        # 2. [multiline(name="...", end=true)] text
        m_multi = re.match(r"^\[multiline\((.*?)\)\](.*)$", line, re.IGNORECASE)
        if m_multi:
            attrs = _parse_attrs(m_multi.group(1))
            part = _clean_avg_text(m_multi.group(2), lang)
            if "name" in attrs and not multiline_buf:
                multiline_spk = _clean_avg_text(attrs["name"], lang)
            if part:
                multiline_buf.append(part)
            if attrs.get("end", "").lower() == "true":
                joined = "".join(multiline_buf).strip()
                if joined:
                    tokens.append({"kind": "utterance", "speaker": multiline_spk, "text": joined})
                multiline_buf = []
                multiline_spk = ""
            continue

        # Flush any dangling multiline buffer before other directives
        if multiline_buf:
            joined = "".join(multiline_buf).strip()
            if joined:
                tokens.append({"kind": "utterance", "speaker": multiline_spk, "text": joined})
            multiline_buf = []
            multiline_spk = ""

        # 3. Other bracketed directives
        m_dir = re.match(r"^\[([A-Za-z0-9_]+)(?:\((.*)\))?\](.*)$", line)
        if m_dir:
            dname = m_dir.group(1).lower()
            attr_str = m_dir.group(2) or ""
            trailing = m_dir.group(3).strip()
            attrs = _parse_attrs(attr_str) if attr_str else {}

            if dname == "decision":
                opts_raw = attrs.get("options", "")
                vals_raw = attrs.get("values", "")
                opts = [_clean_avg_text(o, lang) for o in opts_raw.split(";")] if opts_raw else []
                vals = [v.strip() for v in vals_raw.split(";") if v.strip()]
                if not vals:
                    vals = [str(i + 1) for i in range(len(opts))]
                while len(opts) < len(vals):
                    # A structural branch without a label is not source prose.
                    # Do not manufacture text that can masquerade as a translation.
                    opts.append("")
                tokens.append({"kind": "decision", "options": opts[: len(vals)], "values": vals})

            elif dname == "predicate":
                refs_raw = attrs.get("references")
                if refs_raw is None or not refs_raw.strip():
                    tokens.append({"kind": "predicate", "refs": None})
                else:
                    refs = [r.strip() for r in refs_raw.split(";") if r.strip()]
                    tokens.append({"kind": "predicate", "refs": refs})

            elif dname in ("subtitle", "sticker", "animtext"):
                txt = _clean_avg_text(attrs.get("text", "") or trailing, lang)
                if txt:
                    tokens.append({"kind": "utterance", "speaker": "", "text": txt})
            # All pure visual/audio directives (Dialog, Blocker, Character, PlayMusic, Delay, HEADER, etc.) ignored
            continue

        # 4. Bare narration line (modern AVG scripts without [name=""])
        if not line.startswith("["):
            txt = _clean_avg_text(line, lang)
            if txt:
                tokens.append({"kind": "utterance", "speaker": "", "text": txt})

    if multiline_buf:
        joined = "".join(multiline_buf).strip()
        if joined:
            tokens.append({"kind": "utterance", "speaker": multiline_spk, "text": joined})

    return tokens


def _split_by_anchors(tokens: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    """
    Split token stream into structural anchors (decision / predicate) and utterance buckets
    between anchors, so multi-language alignment never drifts across branch boundaries.
    """
    anchors: List[Dict[str, Any]] = []
    buckets: List[List[Dict[str, Any]]] = [[]]
    for tok in tokens:
        if tok["kind"] in ("decision", "predicate"):
            anchors.append(tok)
            buckets.append([])
        else:
            buckets[-1].append(tok)
    return anchors, buckets


def _det_node_id(scene_id: str, index: int) -> int:
    digest = hashlib.sha256(f"{scene_id}:node:{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:6], "big") % (10**14) + 100000


def _has_source_text(tokens: List[Dict[str, Any]]) -> bool:
    """Whether this locale supplies real prose, including choice-only scenes."""
    return any(
        (token["kind"] == "utterance" and bool(token["text"].strip()))
        or (token["kind"] == "decision" and any(text.strip() for text in token["options"]))
        for token in tokens
    )


def _normalize_structure(tokens: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    """Ignore ineffective bare predicates; reject references without a scope."""
    result = []
    scopes: List[Set[str]] = []
    selected: List[bool] = []
    for token in tokens:
        if token["kind"] == "predicate":
            refs = token["refs"]
            if not scopes:
                if refs:
                    raise ValueError(f"Unscoped predicate references {refs}: {source}")
                continue
            if refs is None:
                scopes.pop()
                selected.pop()
            else:
                wanted = set(refs)
                matches = [i for i, scope in enumerate(scopes) if wanted <= scope]
                if not matches:
                    raise ValueError(f"Unknown predicate references {refs}: {source}")
                match = matches[-1]
                del scopes[match + 1:]
                del selected[match + 1:]
                if wanted == scopes[-1]:
                    scopes.pop()
                    selected.pop()
                else:
                    selected[-1] = True
        else:
            if scopes and not selected[-1]:
                scopes.pop()
                selected.pop()
            if token["kind"] == "decision":
                values = token["values"]
                if not values or len(values) != len(set(values)):
                    raise ValueError(f"Empty or duplicate decision values: {source}")
                scopes.append(set(values))
                selected.append(False)
        result.append(token)
    return result


def _anchor_signature(anchor: Dict[str, Any]) -> tuple:
    if anchor["kind"] == "decision":
        return ("decision", tuple(sorted(anchor["values"])))
    refs = anchor["refs"]
    return ("predicate", None if refs is None else tuple(sorted(refs)))


def _compile_stream(stream: List[Dict[str, Any]], scene_id: str) -> Dict[str, Any]:
    """Maintain nested branch frontiers and explicit invisible join nodes."""
    nodes: List[Dict[str, Any]] = []
    lines: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = []
    frontier: List[Dict[str, Any]] = []

    def node() -> Dict[str, Any]:
        index = len(nodes) + 1
        value = {"id": _det_node_id(scene_id, index), "sourceIndex": index,
                 "mode": 0, "events": [], "edges": []}
        nodes.append(value)
        return value

    def connect(endpoints: List[Dict[str, Any]], target: Dict[str, Any]) -> None:
        for endpoint in endpoints:
            if "edges" in endpoint:
                if not any(edge["target"] == target["id"] for edge in endpoint["edges"]):
                    endpoint["edges"].append({"target": target["id"], "label": ""})
            elif endpoint["target"] is None:
                endpoint["target"] = target["id"]

    def current() -> List[Dict[str, Any]]:
        if not stack:
            return frontier
        scope = stack[-1]
        return [end for value in scope["active"] for end in scope["tails"][value]]

    def advance(value: Dict[str, Any]) -> None:
        nonlocal frontier
        if stack:
            for ref in stack[-1]["active"]:
                stack[-1]["tails"][ref] = [value]
        else:
            frontier = [value]

    def close() -> None:
        scope = stack.pop()
        join = node()
        connect([end for ends in scope["tails"].values() for end in ends], join)
        advance(join)

    for item in stream:
        kind = item["kind"]
        if kind == "predicate":
            if not stack:
                continue
            refs = item["refs"]
            if refs is None:
                close()
            else:
                wanted = set(refs)
                matches = [i for i, scope in enumerate(stack) if wanted <= set(scope["values"])]
                if not matches:
                    raise ValueError(f"Unknown predicate references {refs}: {scene_id}")
                while len(stack) - 1 > matches[-1]:
                    close()
                if wanted == set(stack[-1]["values"]):
                    close()
                else:
                    stack[-1]["active"] = [v for v in stack[-1]["values"] if v in wanted]
            continue
        if stack and not stack[-1]["active"]:
            close()
        value = node()
        connect(current(), value)
        advance(value)
        line_id = f"{scene_id}:{value['id']}"
        value["events"].append(line_id)
        if kind == "utterance":
            line = {"id": line_id, "nodeId": value["id"], "type": "dialogue"}
            line.update(item["texts"])
            line.update({f"spk_{lang}": speaker for lang, speaker in item["speakers"].items()})
        else:
            options = [{"id": f"{line_id}-option-{i}", "target": None,
                        **{lang: opt.get(lang, "") for lang in LANGUAGES}}
                       for i, opt in enumerate(item["options"], 1)]
            line = {"id": line_id, "nodeId": value["id"], "type": "choice", "options": options}
            stack.append({"values": item["values"], "active": [],
                          "tails": {ref: [opt] for ref, opt in zip(item["values"], options)}})
        lines.append(line)
    while stack:
        close()
    by_id = {value["id"]: value for value in nodes}
    for line in lines:
        if line["type"] == "choice":
            by_id[line["nodeId"]]["edges"] = [
                {"target": opt["target"], "label": ""} for opt in line["options"] if opt["target"] is not None
            ]
    return {"id": scene_id, "nodes": nodes, "lines": lines,
            "entryNodeId": nodes[0]["id"] if nodes else None}


def _merge_tokens(tokens_by_lang: Dict[str, list], base_lang: str) -> list:
    split = {lang: _split_by_anchors(tokens) for lang, tokens in tokens_by_lang.items()}
    anchors, buckets = split[base_lang]
    stream = []
    for index in range(len(buckets)):
        length = max(len(parts[1][index]) for parts in split.values())
        for row in range(length):
            entries = {lang: parts[1][index][row] for lang, parts in split.items()
                       if row < len(parts[1][index])}
            stream.append({"kind": "utterance", "texts": {l: t["text"] for l, t in entries.items()},
                           "speakers": {l: t["speaker"] for l, t in entries.items()}})
        if index == len(anchors):
            continue
        anchor = anchors[index]
        if anchor["kind"] == "predicate":
            stream.append(anchor)
        else:
            options = []
            for ref in anchor["values"]:
                option = {"value": ref}
                for lang, (localized, _) in split.items():
                    choice = localized[index]
                    option[lang] = choice["options"][choice["values"].index(ref)]
                options.append(option)
            stream.append({"kind": "decision", "values": anchor["values"], "options": options})
    return stream


def compile_scene_from_repo(
    provider: ExternalRepoProvider, scene_meta: Dict[str, Any], active_langs: List[str],
    use_cache: bool = True,
) -> Dict[str, Any]:
    path = f"story/{scene_meta['storyTxt']}.txt"
    requested = list(dict.fromkeys(active_langs))
    if not requested or any(lang not in LANGUAGES for lang in requested):
        raise ValueError(f"Unsupported or empty requested languages: {requested}")
    raw = {lang: text for lang in requested
           if (text := provider.fetch_text(lang, path, use_cache=use_cache))}
    if not raw:
        raise FileNotFoundError(f"Story script not found: {path}")
    tokens = {lang: _normalize_structure(parse_raw_avg_tokens(text, lang), f"{lang}/{path}")
              for lang, text in raw.items() if lang in requested}
    readable = [lang for lang, items in tokens.items() if _has_source_text(items)]
    active = {lang: tokens[lang] for lang in requested if lang in readable}
    if not active:
        active = {lang: tokens[lang] for lang in readable}
    if not active:
        active = {requested[0]: []}
    signatures = {lang: [_anchor_signature(a) for a in _split_by_anchors(items)[0]]
                  for lang, items in active.items()}
    base = next(iter(active))
    mismatch = any(signature != signatures[base] for signature in signatures.values())
    scene_id = scene_meta["id"]
    if mismatch:
        scenes = {lang: _compile_stream(_merge_tokens({lang: items}, lang), f"{scene_id}_{lang}")
                  for lang, items in active.items()}
        result = {"id": scene_id, "nodes": [], "lines": [], "entryNodeId": None,
                  "alignmentStatus": "separate", "languageScenes": scenes}
    else:
        result = _compile_stream(_merge_tokens(active, base), scene_id)
        result["alignmentStatus"] = "aligned"
    result.update({"availableLanguages": list(raw), "sourceTextLanguages": readable,
                   "requestedLanguages": requested, "tag": scene_meta.get("tag", "")})
    result.update({key: value for key, value in scene_meta.items() if key.startswith("title_")})
    return result


