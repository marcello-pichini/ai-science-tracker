# Claim submissions

Open problems are listed at https://aisciencetracker.org/claims.html and in `data/claims.json`.

1. Open a claim issue: https://github.com/marcello-pichini/ai-science-tracker/issues/new?template=claim.yml
2. Open a pull request that adds one file at `claims/submissions/PROBLEM-ID/YOUR-GITHUB-HANDLE-SHORT-NAME.txt` (or `.json`), in the format given for that problem. Change nothing else.
3. The `Claims` workflow runs `python3 scripts/claims/verify.py PROBLEM-ID FILE` and passes only when the submission beats the recorded baseline.

Put the AI agent and model you used, if any, in the pull request body as `Agent:` and `Model:` lines. A passing check means the submission beats this repository's baseline. A maintainer checks the literature before marking the problem solved.
