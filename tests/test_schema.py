"""Validate the data files against schema/*.schema.json with a small stdlib checker.
shortcut: supports only the keywords the schemas use (type, enum, pattern, min/max, minLength, required, properties,
additionalProperties, items); switch to the jsonschema package if the schemas grow."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = {'object': dict, 'array': list, 'string': str, 'integer': int}


def errors(value, schema, path='$'):
    t = schema.get('type')
    if t and (not isinstance(value, TYPES[t]) or isinstance(value, bool)):
        return [f'{path}: expected {t}']
    out = []
    if 'enum' in schema and value not in schema['enum']:
        out.append(f'{path}: {value!r} not in enum')
    if isinstance(value, str):
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            out.append(f'{path}: does not match {schema["pattern"]}')
        if len(value) < schema.get('minLength', 0):
            out.append(f'{path}: too short')
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get('minimum', value) or value > schema.get('maximum', value):
            out.append(f'{path}: out of range')
    if isinstance(value, dict):
        out += [f'{path}.{k}: required' for k in schema.get('required', []) if k not in value]
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            out += [f'{path}.{k}: unexpected field' for k in value if k not in props]
        for k, sub in props.items():
            if k in value:
                out += errors(value[k], sub, f'{path}.{k}')
    if isinstance(value, list) and 'items' in schema:
        for i, item in enumerate(value):
            out += errors(item, schema['items'], f'{path}[{i}]')
    return out


class SchemaTests(unittest.TestCase):
    def check(self, name):
        schema = json.loads((ROOT / f'schema/{name}.schema.json').read_text())
        data = json.loads((ROOT / f'data/{name}.json').read_text())
        self.assertEqual(errors(data, schema), [])
        self.assertEqual(len({r['id'] for r in data}), len(data))

    def test_discoveries_match_schema(self):
        self.check('discoveries')

    def test_vulnerabilities_match_schema(self):
        self.check('vulnerabilities')

    def test_archived_discoveries_match_schema_and_are_not_active(self):
        schema = json.loads((ROOT / 'schema/discoveries.schema.json').read_text())
        archived = json.loads((ROOT / 'data/archived-discoveries.json').read_text())
        active = json.loads((ROOT / 'data/discoveries.json').read_text())
        self.assertEqual(errors(archived, schema), [])
        self.assertEqual(len({r['id'] for r in archived}), len(archived))
        self.assertFalse({r['id'] for r in archived} & {r['id'] for r in active})

    def test_validator_rejects_bad_records(self):
        schema = json.loads((ROOT / 'schema/discoveries.schema.json').read_text())
        bad = dict(json.loads((ROOT / 'data/discoveries.json').read_text())[0], field='cooking', extra=1)
        bad['relevance'] = {'impact': 9, 'validation': 3, 'novelty': 3}
        found = ' '.join(errors([bad], schema))
        for expected in ('not in enum', 'unexpected field', 'out of range'):
            self.assertIn(expected, found)


if __name__ == '__main__':
    unittest.main()
