#!/usr/bin/env python3
"""Extract and merge discovery-summary translations.

The locale pages read only ``summary`` from ``i18n/discoveries/<lang>.json``,
keyed by discovery id (``localizedSummary`` in ``index.html``). A missing
summary stays in English. Titles, paper names, source links and evidence
fields are not in that file and are left unchanged.

Merge is idempotent and resumable: an existing non-empty summary is never
replaced, and one translation is copied to every entry that still has the
same English summary. Re-run ``extract`` after new discoveries are added;
already translated strings are omitted.

    python3 scripts/i18n_discoveries.py status
    python3 scripts/i18n_discoveries.py extract --lang it --out work/i18n/it
    python3 scripts/i18n_discoveries.py verify --lang it \\
        --source work/i18n/it/batch-001.jsonl --translated work/i18n/it/done-001.jsonl
    python3 scripts/i18n_discoveries.py merge --lang it \\
        --against work/i18n/it/batch-001.jsonl work/i18n/it/done-001.jsonl
    python3 scripts/i18n_discoveries.py propagate --lang it

``extract`` writes compact JSONL batches (default 120 items), shortest
summaries first, one line per distinct English string:

    {"id": "<discovery id>", "field": "summary", "en": "<english>"}

A translated batch is JSONL (or one JSON object). Each item is either
``{"id": "<id>", "summary": "<text>"}`` or a map of id to text. Pass the
extract batch via ``--against`` so a summary edited after extraction is not
paired with a stale translation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from i18n_site import LOCALES, ROOT, load_json

# index.html reads row.summary only. i18n_site.catalog_errors checks that key.
TRANSLATABLE_FIELDS = ("summary",)

DISCOVERIES = ROOT / "data" / "discoveries.json"
OVERLAY_DIR = ROOT / "i18n" / "discoveries"

NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
URL = re.compile(r"https?://[^\s)>\]]+")
# Names that contain digits (BRCA1, COVID-19, AlphaFold2). Plain acronyms such as AI are not locked.
NAME_DIGIT = re.compile(r"\b(?:[A-Z]{2,}-\d+|[A-Z]{2,}\d+[A-Za-z0-9]*|[A-Z][A-Za-z]*\d+[A-Za-z0-9]*)\b")
SYMBOLS = "αβγδεθλμπσφωΩµμ±×÷≥≤≈°Å"
EN_FUNCTION = {
    "the", "a", "an", "of", "and", "or", "to", "in", "for", "with", "was", "were",
    "is", "are", "be", "been", "this", "that", "these", "those", "from", "by", "on",
    "as", "at", "not", "no", "but", "than", "into", "over", "after", "before",
    "between", "within", "without", "using", "used", "reported", "study", "model",
    "patients", "results", "result", "does", "did", "has", "have", "had", "its",
    "their", "which", "when", "where", "while", "than", "then", "also", "only",
}


def discoveries_path(root: Path) -> Path:
    return root / "data" / "discoveries.json"


def overlay_path(root: Path, lang: str) -> Path:
    return root / "i18n" / "discoveries" / f"{lang}.json"


def load_records(root: Path) -> list[dict]:
    data = json.loads(discoveries_path(root).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{discoveries_path(root)} must be a JSON array")
    return data


def word_count(text: str) -> int:
    return len(text.split())


def preserved_tokens(text: str) -> list[str]:
    tokens = NUMBER.findall(text)
    tokens.extend(match.rstrip(".,;:") for match in URL.findall(text))
    tokens.extend(NAME_DIGIT.findall(text))
    tokens.extend(symbol for symbol in SYMBOLS if symbol in text)
    if "%" in text:
        tokens.append("%")
    # Stable unique list.
    seen = set()
    unique = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def looks_untranslated(source: str, translated: str) -> bool:
    if source.strip() != translated.strip():
        return len(source) > 40 and source.strip() in translated
    words = re.findall(r"[A-Za-z']+", source)
    return sum(1 for word in words if word.lower() in EN_FUNCTION) >= 3


def translation_problems(source: str, translated: str) -> list[str]:
    if not isinstance(translated, str) or not translated.strip():
        return ["empty"]
    translated = translated.strip()
    problems = []
    if looks_untranslated(source, translated):
        problems.append("unchanged")
    for token in preserved_tokens(source):
        if token not in translated:
            problems.append(f"missing-token:{token}")
    if len(source) >= 40 and len(translated) < len(source) * 0.4:
        problems.append("too-short")
    return problems


def group_sources(records: list[dict], field: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    by_id = {}
    by_text = defaultdict(list)
    for record in records:
        text = record.get(field) or ""
        if not isinstance(text, str):
            continue
        by_id[record["id"]] = text
        by_text[text].append(record["id"])
    return by_id, by_text


def present_texts(overlay: dict, by_id: dict[str, str], field: str) -> set[str]:
    found = set()
    for entry_id, source in by_id.items():
        row = overlay.get(entry_id)
        if isinstance(row, dict) and isinstance(row.get(field), str) and row[field].strip():
            found.add(source)
    return found


def missing_items(records: list[dict], overlay: dict, fields: tuple[str, ...],
                  min_words: int = 0, max_words: int | None = None) -> list[dict]:
    """One item per missing English string, shortest first."""
    items = []
    for field in fields:
        by_id, _by_text = group_sources(records, field)
        done = present_texts(overlay, by_id, field)
        seen = set()
        ordered = sorted(by_id.items(), key=lambda item: (word_count(item[1]), item[0]))
        for entry_id, text in ordered:
            if not text.strip() or text in done or text in seen:
                continue
            count = word_count(text)
            if count < min_words or (max_words is not None and count > max_words):
                continue
            seen.add(text)
            items.append({"id": entry_id, "field": field, "en": text, "words": count})
    items.sort(key=lambda item: (TRANSLATABLE_FIELDS.index(item["field"]), item["words"], item["id"]))
    return items


def write_batches(items: list[dict], out_dir: Path, batch_size: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    size = max(1, batch_size)
    for index in range(0, len(items), size):
        chunk = items[index:index + size]
        path = out_dir / f"batch-{index // size + 1:03d}.jsonl"
        lines = []
        for item in chunk:
            lines.append(json.dumps(
                {"id": item["id"], "field": item["field"], "en": item["en"]},
                ensure_ascii=False,
            ))
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        paths.append(path)
    return paths


def load_jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("[") or (text.startswith("{") and "\n" not in text):
        payload = json.loads(text)
        if isinstance(payload, list):
            rows = []
            for item in payload:
                rows.extend(records_from_obj(item))
            return rows
        return records_from_obj(payload)
    rows = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.extend(records_from_obj(json.loads(line)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{lineno}: {exc}") from exc
    return rows


def records_from_obj(obj) -> list[dict]:
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    if isinstance(obj.get("id"), str):
        field = obj.get("field") or "summary"
        if field not in TRANSLATABLE_FIELDS:
            raise ValueError(f"field {field!r} is not read from the discovery overlay")
        text = obj.get(field, obj.get("text"))
        row = {"id": obj["id"], "field": field, "text": text}
        if isinstance(obj.get("en"), str):
            row["en"] = obj["en"]
        return [row]
    if obj and all(isinstance(value, str) for value in obj.values()):
        return [{"id": key, "field": "summary", "text": value} for key, value in obj.items()]
    raise ValueError("expected {id, summary} or an id-to-text map")


def iter_translation_files(paths: list[Path]) -> list[Path]:
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("done-*.jsonl")))
        else:
            files.append(path)
    return files


def against_sources(paths: list[Path]) -> dict[str, str]:
    sources = {}
    for path in paths:
        for row in load_jsonl(path):
            english = row.get("en")
            if isinstance(english, str):
                sources[row["id"]] = english
            elif "text" in row and row.get("field") == "summary" and isinstance(row.get("text"), str):
                # extract batches use "en"; ignore translation rows
                continue
    return sources


def propagate(overlay: dict, records: list[dict]) -> int:
    """Copy an existing summary onto entries that share its English text."""
    filled = 0
    for field in TRANSLATABLE_FIELDS:
        _by_id, by_text = group_sources(records, field)
        for entry_ids in by_text.values():
            existing = []
            for entry_id in entry_ids:
                row = overlay.get(entry_id)
                if isinstance(row, dict) and isinstance(row.get(field), str) and row[field].strip():
                    existing.append(row[field])
            if not existing:
                continue
            # Distinct translations of the same English stay as they are.
            fill = existing[0]
            if any(value != fill for value in existing):
                continue
            for entry_id in entry_ids:
                row = overlay.get(entry_id)
                if isinstance(row, dict) and isinstance(row.get(field), str) and row[field].strip():
                    continue
                overlay.setdefault(entry_id, {})[field] = fill
                filled += 1
    return filled


def write_overlay(path: Path, overlay: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: overlay[key] for key in sorted(overlay)}
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_translations(overlay: dict, records: list[dict], translated: list[dict],
                       against: dict[str, str] | None = None) -> dict:
    by_id, _by_text = group_sources(records, "summary")
    result = {"merged": 0, "skipped": 0, "rejected": 0, "stale": 0, "problems": []}
    for row in translated:
        entry_id = row["id"]
        field = row["field"]
        if entry_id not in by_id:
            result["rejected"] += 1
            result["problems"].append({"id": entry_id, "reason": "unknown-id"})
            continue
        source = by_id[entry_id]
        if against is not None and entry_id in against and against[entry_id] != source:
            result["stale"] += 1
            result["problems"].append({"id": entry_id, "reason": "stale"})
            continue
        current = overlay.get(entry_id)
        if isinstance(current, dict) and isinstance(current.get(field), str) and current[field].strip():
            result["skipped"] += 1
            continue
        problems = translation_problems(source, row["text"])
        if problems:
            result["rejected"] += 1
            result["problems"].append({"id": entry_id, "reason": ",".join(problems)})
            continue
        overlay.setdefault(entry_id, {})[field] = row["text"].strip()
        result["merged"] += 1
    result["propagated"] = propagate(overlay, records)
    return result


def coverage(overlay: dict, records: list[dict]) -> list[tuple[str, int, int]]:
    rows = []
    for field in TRANSLATABLE_FIELDS:
        by_id, _by_text = group_sources(records, field)
        done = 0
        for entry_id in by_id:
            row = overlay.get(entry_id)
            if isinstance(row, dict) and isinstance(row.get(field), str) and row[field].strip():
                done += 1
        rows.append((field, done, len(by_id)))
    return rows


def conflicts(overlay: dict, records: list[dict]) -> int:
    count = 0
    for field in TRANSLATABLE_FIELDS:
        _by_id, by_text = group_sources(records, field)
        for entry_ids in by_text.values():
            values = []
            for entry_id in entry_ids:
                row = overlay.get(entry_id)
                if isinstance(row, dict) and isinstance(row.get(field), str) and row[field].strip():
                    values.append(row[field])
            if len(set(values)) > 1:
                count += 1
    return count


def command_status(root: Path, langs: list[str]) -> int:
    records = load_records(root)
    print("translatable: " + ", ".join(TRANSLATABLE_FIELDS))
    for lang in langs:
        overlay = load_json(overlay_path(root, lang))
        for field, done, total in coverage(overlay, records):
            print(f"{lang} {field} {done}/{total} missing {total - done}")
        orphan = sorted(set(overlay) - {record["id"] for record in records})
        clash = conflicts(overlay, records)
        if orphan:
            print(f"{lang} orphan-ids {len(orphan)}")
        if clash:
            print(f"{lang} conflicting-duplicates {clash}")
    return 0


def command_extract(root: Path, lang: str, out_dir: Path, batch_size: int,
                    min_words: int, max_words: int | None, fields: tuple[str, ...]) -> int:
    records = load_records(root)
    overlay = load_json(overlay_path(root, lang))
    items = missing_items(records, overlay, fields, min_words=min_words, max_words=max_words)
    paths = write_batches(items, out_dir, batch_size)
    print(
        f"{lang}: {len(items)} missing strings, {len(paths)} batches, "
        f"words {min_words}-{max_words if max_words is not None else 'inf'}, dir {out_dir}"
    )
    return 0


def command_verify(root: Path, lang: str, source: Path, translated: Path) -> int:
    del lang
    records = load_records(root)
    by_id, _by_text = group_sources(records, "summary")
    expected = {row["id"]: row["en"] for row in load_jsonl(source)}
    found = {row["id"]: row["text"] for row in load_jsonl(translated)}
    problems = []
    for entry_id, english in expected.items():
        if entry_id not in found:
            problems.append(f"{entry_id} missing")
            continue
        current = by_id.get(entry_id)
        if current is not None and current != english:
            problems.append(f"{entry_id} stale")
            continue
        for problem in translation_problems(english, found[entry_id]):
            problems.append(f"{entry_id} {problem}")
    extra = sorted(set(found) - set(expected))
    for entry_id in extra:
        problems.append(f"{entry_id} extra")
    if problems:
        print("\n".join(problems[:40]))
        if len(problems) > 40:
            print(f"... {len(problems) - 40} more")
        print(f"verify failed: {len(problems)}")
        return 1
    print(f"verify ok: {len(expected)}")
    return 0


def command_merge(root: Path, lang: str, batches: list[Path], against: list[Path], strict: bool) -> int:
    records = load_records(root)
    path = overlay_path(root, lang)
    overlay = load_json(path)
    before = json.dumps(overlay, ensure_ascii=False, sort_keys=True)
    translated = []
    for batch in iter_translation_files(batches):
        translated.extend(load_jsonl(batch))
    sources = against_sources(against) if against else None
    result = merge_translations(overlay, records, translated, sources)
    after = json.dumps(overlay, ensure_ascii=False, sort_keys=True)
    if after != before:
        write_overlay(path, overlay)
    print(
        f"{lang}: merged {result['merged']}, skipped {result['skipped']}, "
        f"propagated {result['propagated']}, rejected {result['rejected']}, stale {result['stale']}"
    )
    if result["problems"]:
        preview = "\n".join(f"{item['id']} {item['reason']}" for item in result["problems"][:30])
        print(preview)
        if len(result["problems"]) > 30:
            print(f"... {len(result['problems']) - 30} more")
    if strict and (result["rejected"] or result["stale"]):
        return 1
    return 0


def command_propagate(root: Path, lang: str) -> int:
    records = load_records(root)
    path = overlay_path(root, lang)
    overlay = load_json(path)
    before = json.dumps(overlay, ensure_ascii=False, sort_keys=True)
    filled = propagate(overlay, records)
    after = json.dumps(overlay, ensure_ascii=False, sort_keys=True)
    if after != before:
        write_overlay(path, overlay)
    print(f"{lang}: propagated {filled}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract and merge discovery summary translations.")
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="cmd", required=True)

    status = sub.add_parser("status", help="show how many summaries are still English")
    status.add_argument("--lang", action="append", choices=LOCALES)

    extract = sub.add_parser("extract", help="write JSONL batches of missing summaries")
    extract.add_argument("--lang", required=True, choices=LOCALES)
    extract.add_argument("--out", required=True, type=Path)
    extract.add_argument("--batch-size", type=int, default=120)
    extract.add_argument("--min-words", type=int, default=0)
    extract.add_argument("--max-words", type=int)
    extract.add_argument("--field", action="append", choices=TRANSLATABLE_FIELDS)

    verify = sub.add_parser("verify", help="check a translated batch without writing")
    verify.add_argument("--lang", required=True, choices=LOCALES)
    verify.add_argument("--source", required=True, type=Path)
    verify.add_argument("--translated", required=True, type=Path)

    merge = sub.add_parser("merge", help="merge translated JSONL into the locale file")
    merge.add_argument("--lang", required=True, choices=LOCALES)
    merge.add_argument("--against", action="append", type=Path, default=[])
    merge.add_argument("--strict", action="store_true")
    merge.add_argument("batches", nargs="+", type=Path)

    propagate = sub.add_parser("propagate", help="copy translations across identical English summaries")
    propagate.add_argument("--lang", required=True, choices=LOCALES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root
    if args.cmd == "status":
        return command_status(root, args.lang or list(LOCALES))
    if args.cmd == "extract":
        fields = tuple(args.field) if args.field else TRANSLATABLE_FIELDS
        return command_extract(root, args.lang, args.out, args.batch_size, args.min_words, args.max_words, fields)
    if args.cmd == "verify":
        return command_verify(root, args.lang, args.source, args.translated)
    if args.cmd == "merge":
        return command_merge(root, args.lang, args.batches, args.against, args.strict)
    if args.cmd == "propagate":
        return command_propagate(root, args.lang)
    raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
