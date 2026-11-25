"""Plain-language evidence levels shared by discovery pages, the home page and Insights.

A level is derived only from the record's own ``evidence.test_type``; it describes the
strongest test the original source reports, never an independent verification by this site.
"""
import html

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
