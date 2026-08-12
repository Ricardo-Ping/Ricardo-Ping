#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional

README_PATH = Path("README.md")
SEED_PATH = Path("data/publications_seed.json")
CACHE_PATH = Path("data/publications_cache.json")
START_MARKER = "<!-- PUBS:START -->"
END_MARKER = "<!-- PUBS:END -->"


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_text(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def doi_to_url(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return f"https://doi.org/{doi}"


def normalize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    authors = [a.strip() for a in entry.get("authors", []) if str(a).strip()]
    return {
        "year": int(entry.get("year", 0) or 0),
        "title": str(entry.get("title", "")).strip(),
        "authors": authors,
        "venue": str(entry.get("venue", "")).strip(),
        "doi": (entry.get("doi") or "").strip() or None,
        "paper_url": (entry.get("paper_url") or "").strip() or None,
        "citations": entry.get("citations", None),
    }


def get_citation_badge_base_url() -> str:
    return os.getenv("PUBLICATION_CITATION_BADGE_BASE_URL", "").strip().rstrip("/")


def normalize_title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()


def title_similarity(left: str, right: str) -> float:
    left_key = normalize_title_key(left)
    right_key = normalize_title_key(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def load_seed() -> List[Dict[str, Any]]:
    if not SEED_PATH.exists():
        return []
    # Accept UTF-8 with or without BOM to keep CI resilient to editor encoding differences.
    data = json.loads(SEED_PATH.read_text(encoding="utf-8-sig"))
    return [normalize_entry(x) for x in data]


def load_cache() -> List[Dict[str, Any]]:
    if not CACHE_PATH.exists():
        return []
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8-sig"))
    return [normalize_entry(x) for x in data]


def write_cache(entries: List[Dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def build_seed_index(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for raw_entry in entries:
        entry = normalize_entry(raw_entry)
        key = normalize_title_key(entry.get("title", ""))
        if key:
            index[key] = entry
    return index


def preserve_curated_metadata(
    entries: List[Dict[str, Any]],
    seed_index: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged_entries: List[Dict[str, Any]] = []
    seen_keys = set()

    for raw_entry in entries:
        entry = normalize_entry(raw_entry)
        key = normalize_title_key(entry.get("title", ""))
        curated = seed_index.get(key)

        if curated:
            # Prefer curated local metadata for stable fields like title casing and DOI links.
            entry["title"] = curated.get("title") or entry["title"]
            if not entry.get("authors"):
                entry["authors"] = curated.get("authors") or []
            if not entry.get("venue"):
                entry["venue"] = curated.get("venue") or ""
            if not entry.get("year"):
                entry["year"] = curated.get("year") or 0
            if not entry.get("doi"):
                entry["doi"] = curated.get("doi")
            if not entry.get("paper_url"):
                entry["paper_url"] = curated.get("paper_url")
            seen_keys.add(key)

        merged_entries.append(entry)

    for key, curated in seed_index.items():
        if key not in seen_keys:
            merged_entries.append(normalize_entry(curated))

    return merged_entries


def extract_orcid_external_ids(work: Dict[str, Any]) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    groups = work.get("external-ids", {}).get("external-id", []) or []
    for item in groups:
        id_type = (item.get("external-id-type") or "").lower()
        id_value = item.get("external-id-value") or ""
        if id_type and id_value:
            ids[id_type] = id_value
    return ids


def fetch_orcid_publications(orcid_id: str) -> List[Dict[str, Any]]:
    headers = {"Accept": "application/json"}
    root = f"https://pub.orcid.org/v3.0/{orcid_id}"
    works = fetch_json(f"{root}/works", headers=headers)
    groups = works.get("group", []) or []
    out: List[Dict[str, Any]] = []

    for g in groups:
        summaries = g.get("work-summary", []) or []
        if not summaries:
            continue
        put_code = summaries[0].get("put-code")
        if not put_code:
            continue
        detail = fetch_json(f"{root}/work/{put_code}", headers=headers)

        title = detail.get("title", {}).get("title", {}).get("value", "").strip()
        if not title:
            continue

        journal = detail.get("journal-title", {}).get("value", "").strip()
        year_str = detail.get("publication-date", {}).get("year", {}).get("value")
        year = int(year_str) if year_str and str(year_str).isdigit() else 0

        contributors = detail.get("contributors", {}).get("contributor", []) or []
        authors: List[str] = []
        for c in contributors:
            name = c.get("credit-name", {}).get("value", "").strip()
            if name:
                authors.append(name)

        ids = extract_orcid_external_ids(detail)
        doi = ids.get("doi")
        url = detail.get("url", {}).get("value")

        out.append(
            normalize_entry(
                {
                    "year": year,
                    "title": title,
                    "authors": authors,
                    "venue": journal,
                    "doi": doi,
                    "paper_url": url,
                }
            )
        )

    return out


def fetch_scholar_publications(user_id: str) -> List[Dict[str, Any]]:
    url = (
        "https://scholar.google.com/citations?"
        + urllib.parse.urlencode(
            {
                "user": user_id,
                "hl": "en",
                "view_op": "list_works",
                "sortby": "pubdate",
                "pagesize": "100",
            }
        )
    )
    html = fetch_text(url, headers={"User-Agent": "Mozilla/5.0"})
    rows = re.findall(r'<tr class="gsc_a_tr".*?</tr>', html, flags=re.S)

    out: List[Dict[str, Any]] = []
    for row in rows:
        title_m = re.search(r'class="gsc_a_at"[^>]*>(.*?)</a>', row, flags=re.S)
        if not title_m:
            continue
        title = unescape(re.sub(r"<.*?>", "", title_m.group(1))).strip()

        gray = re.findall(r'<div class="gs_gray">(.*?)</div>', row, flags=re.S)
        authors = []
        venue = ""
        if gray:
            authors = [x.strip() for x in unescape(re.sub(r"<.*?>", "", gray[0])).split(",") if x.strip()]
        if len(gray) > 1:
            venue = unescape(re.sub(r"<.*?>", "", gray[1])).strip()

        year_m = re.search(r'<span class="gsc_a_h gsc_a_hc gs_ibl">(\d{4})</span>', row)
        year = int(year_m.group(1)) if year_m else 0

        cited_m = re.search(r'class="gsc_a_ac gs_ibl">(\d+)</a>', row)
        citations = int(cited_m.group(1)) if cited_m else None

        out.append(
            normalize_entry(
                {
                    "year": year,
                    "title": title,
                    "authors": authors,
                    "venue": venue,
                    "citations": citations,
                }
            )
        )

    return out


def enrich_with_crossref(entries: List[Dict[str, Any]]) -> None:
    for entry in entries:
        if entry.get("doi") and entry.get("authors") and entry.get("venue"):
            continue

        query = urllib.parse.quote(entry["title"])
        url = f"https://api.crossref.org/works?query.bibliographic={query}&rows=5"
        try:
            result = fetch_json(url)
            items = result.get("message", {}).get("items") or []
        except Exception:
            continue

        best_item = None
        best_score = 0.0
        for candidate in items:
            titles = candidate.get("title") or []
            candidate_title = titles[0] if titles else ""
            score = title_similarity(entry["title"], candidate_title)
            if score > best_score:
                best_score = score
                best_item = candidate

        if not best_item or best_score < 0.88:
            continue

        if not entry.get("doi") and best_item.get("DOI"):
            entry["doi"] = best_item["DOI"]

        if not entry.get("venue"):
            container = best_item.get("container-title") or []
            if container:
                entry["venue"] = container[0]

        if not entry.get("authors"):
            authors = []
            for author in best_item.get("author", []) or []:
                given = author.get("given", "").strip()
                family = author.get("family", "").strip()
                name = f"{given} {family}".strip()
                if name:
                    authors.append(name)
            if authors:
                entry["authors"] = authors


def fetch_openalex_work(doi: Optional[str], title: str) -> Optional[Dict[str, Any]]:
    mailto = os.getenv("OPENALEX_EMAIL", "").strip()

    if doi:
        doi_path = urllib.parse.quote(doi_to_url(doi) or "", safe="")
        params = {"mailto": mailto} if mailto else None
        url = "https://api.openalex.org/works/" + doi_path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            return fetch_json(url)
        except Exception:
            pass

    if not title:
        return None

    params = {"search": title, "per-page": "5"}
    if mailto:
        params["mailto"] = mailto
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    result = fetch_json(url)
    candidates = result.get("results") or []

    best_match = None
    best_score = 0.0
    for candidate in candidates:
        candidate_title = candidate.get("display_name") or ""
        score = title_similarity(title, candidate_title)
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_match and best_score >= 0.88:
        return best_match
    return None


def enrich_with_openalex_citations(entries: List[Dict[str, Any]]) -> None:
    for entry in entries:
        doi = entry.get("doi")
        title = entry.get("title", "")
        if not doi and not title:
            continue

        try:
            work = fetch_openalex_work(doi, title)
        except Exception:
            continue

        if not work:
            continue

        cited_by_count = work.get("cited_by_count")
        if cited_by_count is not None:
            entry["citations"] = int(cited_by_count)


def is_first_author(entry: Dict[str, Any], primary_last_name: str) -> bool:
    if not entry.get("authors"):
        return False
    first = entry["authors"][0].lower()
    return primary_last_name.lower() in first


def citation_badge(citations: Any) -> str:
    if citations is None:
        return '<img src="https://img.shields.io/badge/Citations-N%2FA-6e7681?style=flat-square" alt="citations n/a"/>'
    return f'<img src="https://img.shields.io/badge/Citations-{citations}-1f6feb?style=flat-square" alt="citations {citations}"/>'


def build_dynamic_citation_badge_url(
    entry: Dict[str, Any],
    citations: Any,
    badge_base_url: str,
) -> Optional[str]:
    if not badge_base_url:
        return None

    doi = entry.get("doi")
    title = entry.get("title")
    if not doi and not title:
        return None

    params: Dict[str, str] = {"label": "OpenAlex"}
    if doi:
        params["doi"] = str(doi)
    elif title:
        params["title"] = str(title)
    if citations is not None:
        params["fallback"] = str(citations)

    return f"{badge_base_url}/badge.svg?{urllib.parse.urlencode(params)}"


def render_citation_badge(entry: Dict[str, Any], badge_base_url: str) -> str:
    dynamic_badge = build_dynamic_citation_badge_url(entry, entry.get("citations"), badge_base_url)
    if dynamic_badge:
        fallback_text = entry.get("citations")
        fallback_suffix = fallback_text if fallback_text is not None else "n/a"
        return f'<img src="{dynamic_badge}" alt="openalex citations {fallback_suffix}"/>'

    return citation_badge(entry.get("citations"))


def render_table(entries: List[Dict[str, Any]], badge_base_url: str) -> str:
    if not entries:
        return "<p>No publications found.</p>"

    lines = ["<table>"]
    for entry in entries:
        link = doi_to_url(entry.get("doi")) or entry.get("paper_url")
        safe_title = entry["title"].replace("|", "\\|")
        title_html = f'<a href="{link}"><strong>{safe_title}</strong></a>' if link else f"<strong>{safe_title}</strong>"
        authors = ", ".join(entry.get("authors") or ["N/A"])
        venue = entry.get("venue") or "N/A"
        links: List[str] = []
        if entry.get("doi"):
            links.append(f'<a href="{doi_to_url(entry["doi"])}">DOI</a>')
        if entry.get("paper_url"):
            links.append(f'<a href="{entry["paper_url"]}">Paper</a>')
        links_html = " | ".join(links) if links else "-"

        lines.append("  <tr>")
        lines.append(f"    <td><strong>{entry.get('year', 0) or 'N/A'}</strong></td>")
        lines.append(f"    <td>{title_html}<br/>Authors: {authors}<br/>{venue}</td>")
        lines.append(f"    <td>{links_html}<br/>{render_citation_badge(entry, badge_base_url)}</td>")
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def render_publication_section(
    entries: List[Dict[str, Any]],
    source_label: str,
    primary_last_name: str,
    badge_base_url: str,
) -> str:
    ordered = sorted(entries, key=lambda entry: (entry.get("year", 0), entry.get("title", "")), reverse=True)
    first = [entry for entry in ordered if is_first_author(entry, primary_last_name)]
    co = [entry for entry in ordered if not is_first_author(entry, primary_last_name)]

    source_line = f"> Auto-synced metadata source: **{source_label}**"
    if badge_base_url:
        source_line += " · live citation badges: **OpenAlex**"

    parts = [
        START_MARKER,
        source_line,
        "",
        "## Publications (First Author)",
        "",
        render_table(first, badge_base_url),
        "",
        "## Publications (Co-Author)",
        "",
        render_table(co, badge_base_url),
        END_MARKER,
    ]
    return "\n".join(parts)


def replace_between_markers(text: str, replacement: str) -> str:
    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.S)
    if pattern.search(text):
        return pattern.sub(replacement, text)

    anchor = "## GitHub Stats"
    idx = text.find(anchor)
    if idx == -1:
        return text + "\n\n" + replacement + "\n"
    return text[:idx] + replacement + "\n\n" + text[idx:]


def main() -> int:
    source = os.getenv("PUBLICATION_SOURCE", "orcid").strip().lower()
    orcid_id = os.getenv("ORCID_ID", "").strip()
    scholar_id = os.getenv("GOOGLE_SCHOLAR_ID", "").strip()
    primary_last_name = os.getenv("PRIMARY_AUTHOR_LAST_NAME", "ping").strip()
    badge_base_url = get_citation_badge_base_url()

    entries: List[Dict[str, Any]] = []
    seed_entries = load_seed()
    seed_index = build_seed_index(seed_entries)
    source_label = "seed data"
    remote_failed = False

    try:
        if source == "scholar" and scholar_id:
            entries = fetch_scholar_publications(scholar_id)
            source_label = f"Google Scholar ({scholar_id})"
        elif source == "orcid" and orcid_id:
            entries = fetch_orcid_publications(orcid_id)
            source_label = f"ORCID ({orcid_id})"
        elif orcid_id:
            entries = fetch_orcid_publications(orcid_id)
            source_label = f"ORCID ({orcid_id})"
        elif scholar_id:
            entries = fetch_scholar_publications(scholar_id)
            source_label = f"Google Scholar ({scholar_id})"
    except Exception as exc:
        remote_failed = True
        print(f"[warn] remote source fetch failed: {exc}")

    if not entries:
        cached_entries = load_cache()
        if cached_entries:
            entries = cached_entries
            source_label = "cached data"
            if remote_failed:
                print(f"[info] using cached publications from {CACHE_PATH}")
        else:
            entries = seed_entries
            source_label = "seed data"
            if remote_failed:
                print(f"[info] cache empty; using seed publications from {SEED_PATH}")

    entries = preserve_curated_metadata(entries, seed_index)
    enrich_with_crossref(entries)
    enrich_with_openalex_citations(entries)

    if source_label != "seed data":
        write_cache(entries)

    readme = README_PATH.read_text(encoding="utf-8")
    block = render_publication_section(entries, source_label, primary_last_name, badge_base_url)
    updated = replace_between_markers(readme, block)
    README_PATH.write_text(updated, encoding="utf-8")

    print(f"Updated README publications from {source_label}. total={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
