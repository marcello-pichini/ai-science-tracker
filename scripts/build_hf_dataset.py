"""Build the Hugging Face dataset folder: public data files plus a card with current counts."""
import argparse
import datetime
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["discoveries.csv", "discoveries.json", "vulnerabilities.csv", "vulnerabilities.json"]


def size_category(n):
    return "n<1K" if n < 1000 else "1K<n<10K" if n < 10000 else "10K<n<100K"


def build(out, snapshot_date=None):
    snapshot_date = datetime.date.fromisoformat(snapshot_date) if snapshot_date else datetime.date.today()
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copy(ROOT / "data" / name, out / name)
    counts = {k: len(json.loads((ROOT / "data" / f"{k}.json").read_text())) for k in ("discoveries", "vulnerabilities")}
    card = (ROOT / "huggingface" / "README.md").read_text()
    # str.replace, not format: the BibTeX block contains braces
    for key, value in {
        "{discoveries}": counts["discoveries"],
        "{vulnerabilities}": counts["vulnerabilities"],
        "{size}": size_category(max(counts.values())),
        "{date}": snapshot_date.isoformat(),
    }.items():
        card = card.replace(key, str(value))
    (out / "README.md").write_text(card)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, nargs='?', default=Path('hf-build'))
    parser.add_argument('--snapshot-date', help='ISO date of the published catalog snapshot')
    args = parser.parse_args()
    print(build(args.output, args.snapshot_date))
