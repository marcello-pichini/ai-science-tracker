"""Safe downloads: HTTPS only, host allowlist, size cap, sha256 manifest, zip-slip-safe extraction.

Downloaded files are data: they are parsed, never executed. Raw downloads are temporary and are
deleted with cleanup() once the data have been prepared for commit; only the manifest is kept.
"""
import hashlib
import json
import os
import shutil
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "work" / "harvest" / "raw"
MANIFEST = ROOT / "work" / "harvest" / "manifest.jsonl"
ALLOWED_HOSTS = {
    "raw.githubusercontent.com", "github.com", "api.github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com", "osv-vulnerabilities.storage.googleapis.com",
    "bugzilla.mozilla.org", "api.openalex.org", "export.arxiv.org", "api.biorxiv.org",
    "codeload.github.com", "www.anthropic.com", "www.nature.com", "blogs.nvidia.com", "research.google", "www.ebi.ac.uk", "eutils.ncbi.nlm.nih.gov", "ftp.ncbi.nlm.nih.gov", "api.crossref.org",
    "red.anthropic.com", "aisle.com", "xbow.com", "deepmind.google", "research.google", "openai.com",
    "www.microsoft.com", "ai.meta.com", "news.mit.edu", "www.ethz.ch", "ethz.ch",
    "hai.stanford.edu", "bair.berkeley.edu", "ai.epfl.ch", "actu.epfl.ch",
}
MAX_DOWNLOAD = 10 * 1024 ** 3   # bytes; anything larger needs the owner's approval first
MAX_JSON = 200 * 1024 ** 2
MAX_UNZIPPED = 20 * 1024 ** 3
UA = "ai-science-tracker-harvest"


def check_url(url, allowed=ALLOWED_HOSTS):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        raise ValueError(f"only https is allowed: {url}")
    if p.hostname not in allowed:
        raise ValueError(f"host not in the allowlist: {p.hostname}")
    return url


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Every redirect target must also be an allowlisted https host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckedRedirect)


def _user_agent(url):
    # Crossref's polite pool raises rate limits for clients that give a contact; kept out of Git.
    mailto = os.environ.get("CROSSREF_MAILTO", "").strip()
    if mailto and urllib.parse.urlparse(url).hostname == "api.crossref.org":
        return f"{UA} (mailto:{mailto})"
    return UA


def _open(url, timeout=60):
    return _OPENER.open(urllib.request.Request(check_url(url), headers={"User-Agent": _user_agent(url)}), timeout=timeout)


def get_json(url, max_bytes=MAX_JSON, timeout=60):
    with _open(url, timeout) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response larger than {max_bytes} bytes: {url}")
    return json.loads(data)


def get_text(url, max_bytes=MAX_JSON, timeout=60):
    with _open(url, timeout) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response larger than {max_bytes} bytes: {url}")
    return data.decode("utf-8", "replace")


def download(url, source, name=None, max_bytes=MAX_DOWNLOAD, raw=RAW):
    """Stream url into its own new directory; return the file path. Records sha256 in the manifest."""
    dest = Path(raw) / source / time.strftime("%Y%m%dT%H%M%S")
    dest.mkdir(parents=True, exist_ok=False)
    path = dest / (name or Path(urllib.parse.urlparse(url).path).name or "download")
    h, n = hashlib.sha256(), 0
    with _open(url, 120) as r, open(path, "wb") as f:
        length = int(r.headers.get("Content-Length") or 0)
        if length > max_bytes:
            raise ValueError(f"{url} is {length} bytes, over the {max_bytes} cap: ask the owner first")
        while chunk := r.read(1 << 20):
            n += len(chunk)
            if n > max_bytes:
                raise ValueError(f"download exceeded the {max_bytes} cap: {url}")
            h.update(chunk)
            f.write(chunk)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "a", encoding="utf-8") as m:
        m.write(json.dumps({"url": url, "source": source, "bytes": n, "sha256": h.hexdigest(),
                            "date": time.strftime("%Y-%m-%d")}) + "\n")
    return path


def safe_extract(zip_path, dest, max_bytes=MAX_UNZIPPED, max_files=2_000_000):
    """Extract into dest, refusing path traversal, absolute names and zip bombs."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > max_files or sum(i.file_size for i in infos) > max_bytes:
            raise ValueError("archive too large to extract safely")
        for i in infos:
            target = (dest / i.filename).resolve()
            if not str(target).startswith(str(dest) + "/") and target != dest:
                raise ValueError(f"unsafe path in archive: {i.filename}")
        z.extractall(dest)
    return dest


def cleanup(raw=RAW):
    """Delete all raw downloads (the manifest stays)."""
    if Path(raw).exists():
        shutil.rmtree(raw)
