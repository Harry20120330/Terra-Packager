"""Reproducible synthetic cache benchmark; never downloads game resources."""
from __future__ import annotations
import argparse
import json
import os
import tempfile
import time
import tracemalloc
from pathlib import Path

from .repo_provider import ExternalRepoProvider
from .runtime import CURRENT_MEASUREMENTS, Measurements


def catalog_benchmark():
    with tempfile.TemporaryDirectory(prefix="terra_benchmark_") as tmp:
        root = Path(tmp)
        excel = root / "cn/gamedata/excel"
        excel.mkdir(parents=True)
        table = {f"main_{i}": {"name": f"Fictional chapter {i}", "entryType": "MAINLINE",
                               "infoUnlockDatas": [{"storyTxt": f"main/{i}/{j}", "storyName": f"Scene {j}"}
                                                   for j in range(20)]} for i in range(120)}
        (excel / "story_review_table.json").write_text(json.dumps(table), encoding="utf-8")
        metrics = Measurements()
        provider = ExternalRepoProvider(repo_dir=root, measurements=metrics)
        tracemalloc.start()
        started = time.perf_counter()
        for i in range(60):
            provider.resolve_volume(f"main_{i}", ['zh'], use_cache=False)
        indexed_time = time.perf_counter() - started
        _, indexed_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        tracemalloc.start()
        started = time.perf_counter()
        for i in range(60):
            # Reference work performed by the old path: rebuild for each lookup.
            next(v for v in provider._build_catalog(['zh'], False) if v['groupId'] == f'main_{i}')
        repeated_time = time.perf_counter() - started
        _, repeated_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {"volumes": 120, "scenes_per_volume": 20, "lookups": 60,
                "indexed_catalog_builds": metrics.counts['catalog_builds'], "reference_catalog_builds": 60,
                "indexed_seconds": round(indexed_time, 4), "reference_seconds": round(repeated_time, 4),
                "indexed_python_peak_bytes": indexed_peak, "reference_python_peak_bytes": repeated_peak}


def font_benchmark():
    from .epub_builder import _subset_font, FONTS_DIR
    with tempfile.TemporaryDirectory(prefix="terra_font_benchmark_") as tmp:
        previous = os.environ.get('TERRA_CACHE_DIR')
        os.environ['TERRA_CACHE_DIR'] = tmp
        try:
            result = {}
            for label in ('cold', 'warm'):
                metrics = Measurements()
                token = CURRENT_MEASUREMENTS.set(metrics)
                started = time.perf_counter()
                try:
                    _subset_font(FONTS_DIR / 'EBGaramond-Regular.ttf', Path(tmp) / f'{label}.ttf', 'U+0041,U+0042,U+0043')
                finally:
                    CURRENT_MEASUREMENTS.reset(token)
                result[label] = {"seconds": round(time.perf_counter() - started, 4),
                                 "subset_processes": metrics.counts['font_subset_processes'],
                                 "cache_hits": metrics.counts['font_cache_hits']}
            return result
        finally:
            if previous is None:
                os.environ.pop('TERRA_CACHE_DIR', None)
            else:
                os.environ['TERRA_CACHE_DIR'] = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional JSON benchmark report')
    args = parser.parse_args()
    result = {"catalog": catalog_benchmark(), "fonts": font_benchmark(),
              "note": "Synthetic catalog and one Latin font; not a real upstream full-library benchmark. Peaks measure Python allocations, not renderer RSS."}
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
