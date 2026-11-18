"""Reviewed exact source-label grouping shared with the browser entity helper."""
import json
from functools import lru_cache
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parents[1] / 'data/entity-aliases.json'


@lru_cache(maxsize=1)
def entity_map():
    return json.loads(MAP_PATH.read_text(encoding='utf-8'))


def organization(label):
    literal = label.split(';')[0].strip()
    for row in entity_map()['organizations']:
        if literal == row['label'] or literal in row['aliases']:
            return dict(row, source_label=literal)
    return {'id': None, 'label': literal, 'kind': 'unreviewed', 'source_label': literal}
