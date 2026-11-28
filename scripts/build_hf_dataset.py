"""Build the Hugging Face dataset folder: public data files plus a card with current counts.

The global vulnerability dataset is too large for the repository: its files are uploaded to the same Hugging Face
repository under vulnerabilities/ by .github/workflows/vulnerability-dataset.yml; the card counts it from
data/vulnerabilities-overview.json."""
import argparse
import datetime
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["discoveries.csv", "discoveries.json"]


def size_category(n):
    return ("n<1K" if n < 1000 else "1K<n<10K" if n < 10000 else "10K<n<100K" if n < 100000
            else "100K<n<1M" if n < 1000000 else "1M<n<10M")


def build(out, snapshot_date=None):
    snapshot_date = datetime.date.fromisoformat(snapshot_date) if snapshot_date else datetime.date.today()
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copy(ROOT / "data" / name, out / name)
    overview = json.loads((ROOT / "data" / "vulnerabilities-overview.json").read_text())
    counts = {"discoveries": len(json.loads((ROOT / "data" / "discoveries.json").read_text())),
              "vulnerabilities": overview["totals"]["rows"]}
    card = (ROOT / "huggingface" / "README.md").read_text()
    # str.replace, not format: the BibTeX block contains braces
    for key, value in {
        "{discoveries}": counts["discoveries"],
        "{vulnerabilities}": f'{counts["vulnerabilities"]:,}',
        "{vulnerability_sources}": overview["totals"]["sources"],
        "{vulnerability_built}": overview["built"],
        "{vulnerability_source_table}": "\n".join(f'| {s["name"]} | {s["licence"]} | {s["notice"]} |' for s in overview["sources"]),
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
