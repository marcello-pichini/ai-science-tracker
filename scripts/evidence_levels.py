"""Plain-language evidence levels shared by discovery pages, the home page and Insights.

A level is derived only from the record's own ``evidence.test_type``; it describes the
strongest test the original source reports, never an independent verification by this site.
"""
import html
import re

# test_type -> (step 1-4, public label); a record without a known test_type is step 0
LEVELS = {
    'retrospective or benchmark': (1, 'Checked on existing data'),
    'direct test': (2, 'Tested in a new experiment'),
    'prospective or independent check': (3, 'Independently or prospectively checked'),
    'replication or operational use': (4, 'Replicated or in real use'),
}
NOT_REPORTED = (0, 'Test not reported')
HEADING = 'How tested is it?'


def level(record):
    """Return (step, label) for a discovery record."""
    return LEVELS.get((record.get('evidence') or {}).get('test_type'), NOT_REPORTED)


def meter_html(record):
    """Four-step meter plus its label; the label carries the meaning, not the color."""
    step, label = level(record)
    marks = ''.join('<i class="on"></i>' if i < step else '<i></i>' for i in range(4))
    return (f'<span class="evidence-meter"><span class="evidence-steps" role="img" '
            f'aria-label="Step {step} of 4">{marks}</span> '
            f'<span data-i18n>{html.escape(label)}</span></span>')


# Same rule as CatalogUI.abstractOnly() in assets/catalog-ui.js; tests/test_share_pages.py checks they agree.
_NO_FULL_TEXT = re.compile(r'\bfull[- ]?text (?:was )?not (?:accessed|read|reviewed)\b', re.I)
_METHODS = re.compile(r'\bMethods\b')


def abstract_only(record):
    """True when a source-checked record's review scope says only the abstract/metadata was read."""
    scope = str((record.get('source_review') or {}).get('scope') or '')
    return bool(_NO_FULL_TEXT.search(scope)) and not _METHODS.search(scope)
