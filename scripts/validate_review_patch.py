#!/usr/bin/env python3
"""Read-only review/enrichment preflight; untouched unknown historical reviews remain valid."""
import argparse
import datetime
import json
import re
from pathlib import Path


def validate_review_patch(before, after, today=None):
    today = today or datetime.date.today()
    old = {r['id']: r for r in before}
    reviewed = []
    for record in after:
        prior = old.get(record['id'], {})
        review_changed = record.get('source_review') != prior.get('source_review')
        became_checked = record.get('verification_status') == 'verified' and prior.get('verification_status') != 'verified'
        if not (review_changed or became_checked):
            continue
        review = record.get('source_review')
        if not isinstance(review, dict) or not isinstance(review.get('date'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', review['date']):
            raise ValueError(record['id'] + ': changed review/source-check needs its actual review day')
        day = datetime.date.fromisoformat(review['date'])
        if day > today:
            raise ValueError(record['id'] + ': review date cannot be in the future')
        if not isinstance(review.get('scope'), str) or not review['scope'].strip():
            raise ValueError(record['id'] + ': name the bounded source material actually read')
        reviewed.append(record['id'])
    return reviewed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    args = parser.parse_args()
    checked = validate_review_patch(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    print(f'{len(checked)} changed source-review/source-check records pass provenance preflight. Actual source reading remains an editorial responsibility.')


if __name__ == '__main__':
    main()
