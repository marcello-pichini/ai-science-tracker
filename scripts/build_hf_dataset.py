"""Build the Hugging Face dataset folder: public data files plus a card with current counts."""
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["discoveries.csv", "discoveries.json", "vulnerabilities.csv", "vulnerabilities.json"]


def size_category(n):
    return "n<1K" if n < 1000 else "1K<n<10K" if n < 10000 else "10K<n<100K"


def build(out):
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
        "{date}": datetime.date.today().isoformat(),
    }.items():
        card = card.replace(key, str(value))
    (out / "README.md").write_text(card)
    return counts


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "hf-build")))
