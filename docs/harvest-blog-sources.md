# First-party research blog sources

These candidate collectors do not verify scientific admission, modify catalog records or publish anything. Collectors and their coverage reports can be used by a separately configured research workflow.

| Source ID | First-party endpoint | Method |
| --- | --- | --- |
| `microsoft-research` | https://www.microsoft.com/en-us/research/feed/ | Official RSS, linked from Microsoft Research's blog |
| `meta-ai` | https://ai.meta.com/blog/ | HTML listing and exposed Next links |
| `mit-ai` | https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml | Official MIT News AI RSS |
| `eth-news` | https://www.ethz.ch/en/news-und-veranstaltungen/eth-news/news/_jcr_content.feed.html | Official English ETH News feed; broader than AI |
| `stanford-hai` | https://hai.stanford.edu/news | Official HAI HTML listing |
| `berkeley-bair` | https://bair.berkeley.edu/blog/archive/ | Official BAIR archive HTML |
| `epfl-ai` | https://ai.epfl.ch/news/ | Official AI Center HTML, including linked Actu articles |

The Microsoft, MIT and ETH endpoints were identified through first-party feed
links. A web reader's inability to display RSS/XML MIME types does not establish
that their actual payloads were parsed successfully. Synthetic response fixtures
test parser behavior; live source checks must separately record access and dates.

## Run and inspect coverage

From the project root:

```sh
PYTHONPATH=scripts python3 -m harvest.run_blogs --from 2026-11-01 --to 2026-11-18 --out work/harvest/blog-check
```

The command writes `blog-leads.jsonl` and `blog-coverage.json`. A nonzero exit means
one or more sources have partial coverage or access/parser errors; retrieved leads
are still saved. Never interpret that result as no new research. Dates that cannot
be extracted stay unknown and must be checked in the original article. The output
records source URLs, actual fetched listing-page counts, date coverage, matching
window/prior-record counts and any access limitation. No per-source item/page cap
is imposed on exposed HTML Next navigation; repeated-page cycles are reported.

Individual source IDs also work in `scripts/harvest/run_disc.py --sources` and are
included in its `labs` adapter, which now runs by default. Avoid fetching the same
adapters twice in a single research batch. Existing paper/preprint collectors keep
their existing pagination settings; this change does not claim to remove those
independent limits.

## Evidence and coverage limits

RSS exposes the provider's current feed window, not a complete historical archive.
HTML readers follow only source-provided, same-origin listing Next links. Dynamic
Load more controls (notably EPFL) are reported as partial until their underlying
public endpoint is independently identified and implemented. Empty/blocked HTML
and failures on later pages remain explicit, with already retrieved candidates
preserved. Date conflicts between a listing and the article are for the original-source
verification stage to resolve. Generic research, product and institutional news
may enter the candidate queue; inclusion there is not evidence of an AI-enabled
scientific discovery. Scientific admission requires independent original-source evidence review; a successful collector exit alone is not an admission decision.
