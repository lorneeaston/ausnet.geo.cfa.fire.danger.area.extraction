#!/usr/bin/env python3
"""
Download CFA Fire Danger Period restriction maps (one PDF per declaration area).

Scrapes the index page rather than using a hardcoded list, so it survives CFA
renaming or re-splitting areas between seasons. Files land in files/municipalities/.

    pip install requests
    python fetch_cfa_fdp_maps.py
    python fetch_cfa_fdp_maps.py --force --out some/other/dir
"""

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INDEX_URL = (
    "https://www.cfa.vic.gov.au/warnings-restrictions"
    "/fire-danger-period/fire-restriction-dates"
)
DOC_BASE = "https://www.cfa.vic.gov.au/ArticleDocuments/202/"

# hrefs on the page look like ..._MAP_ARARAT_NORTH.pdf.aspx; the .aspx is an
# elcomCMS handler suffix and the bare .pdf URL serves the same bytes.
LINK_RE = re.compile(r"LOCAL_MUNICIPALITY_RESTRICTION_MAP_([A-Z0-9_]+)\.pdf")

EXPECTED_COUNT = 81  # 2024/25 season: 64 councils + 5 unincorporated + 12 splits
USER_AGENT = "Mozilla/5.0 (compatible; fdp-map-fetch/1.0)"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(
        total=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
    return s


def discover(session: requests.Session) -> list[str]:
    """Return sorted unique area slugs (e.g. 'ALPINE', 'YARRIAMBIACK_NORTH')."""
    r = session.get(INDEX_URL, timeout=30)
    r.raise_for_status()
    slugs = sorted(set(LINK_RE.findall(r.text)))
    if not slugs:
        raise SystemExit(
            "No map links found. The page structure has probably changed - "
            f"check {INDEX_URL} by hand."
        )
    return slugs


def fetch_one(session: requests.Session, slug: str, out_dir: Path, force: bool):
    """Download one PDF. Returns (slug, status, detail)."""
    dest = out_dir / f"LOCAL_MUNICIPALITY_RESTRICTION_MAP_{slug}.pdf"
    if dest.exists() and not force:
        return slug, "skip", f"{dest.stat().st_size:,} bytes already on disk"

    url = f"{DOC_BASE}LOCAL_MUNICIPALITY_RESTRICTION_MAP_{slug}.pdf"
    r = session.get(url, timeout=90)
    r.raise_for_status()

    # elcomCMS can answer 200 with an HTML error page, so check the magic bytes
    # rather than trusting the status code or Content-Type.
    if not r.content.startswith(b"%PDF"):
        return slug, "bad", f"not a PDF ({len(r.content):,} bytes, {r.headers.get('Content-Type')})"

    tmp = dest.with_suffix(".pdf.part")
    tmp.write_bytes(r.content)
    tmp.replace(dest)
    return slug, "ok", f"{len(r.content):,} bytes"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="files/municipalities", type=Path)
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    ap.add_argument("--workers", type=int, default=4, help="concurrent downloads")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    session = make_session()

    slugs = discover(session)
    print(f"Found {len(slugs)} declaration areas on the index page.")
    if len(slugs) != EXPECTED_COUNT:
        print(
            f"  note: expected {EXPECTED_COUNT} based on the 2024/25 season - "
            "CFA may have re-split areas, so re-check your LGA join.",
            file=sys.stderr,
        )

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_one, session, s, args.out, args.force): s for s in slugs
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                slug, status, detail = fut.result()
            except Exception as exc:
                status, detail = "fail", str(exc)
            results[slug] = (status, detail)
            print(f"  [{status:>4}] {slug:<32} {detail}")

    manifest = args.out / "manifest.csv"
    with manifest.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["slug", "area_name", "filename", "status"])
        for slug in slugs:
            status, _ = results.get(slug, ("missing", ""))
            w.writerow(
                [
                    slug,
                    slug.replace("_", " ").title(),
                    f"LOCAL_MUNICIPALITY_RESTRICTION_MAP_{slug}.pdf",
                    status,
                ]
            )

    tally = {}
    for status, _ in results.values():
        tally[status] = tally.get(status, 0) + 1
    print(
        "\n"
        + ", ".join(f"{n} {k}" for k, n in sorted(tally.items()))
        + f"\nFiles in {args.out}/, manifest at {manifest}"
    )

    bad = [s for s, (st, _) in results.items() if st in ("fail", "bad")]
    if bad:
        print(f"Problems with: {', '.join(sorted(bad))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())