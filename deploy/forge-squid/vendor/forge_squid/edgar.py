"""SEC EDGAR resolver for the forge-squid graph executor.

Resolves ``<TICKER> 10-K [accession]`` to the filing's primary document, converts the HTML to
plain-text paragraphs (blank-line separated, so forge-dcs ``text_paragraphs`` fragments line up
with 10-K paragraphs), and caches raw HTML on disk. stdlib HTML parsing only; one shared
``httpx.AsyncClient`` passed in by the caller (tests inject a mock transport).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
ACCESSION_RE = re.compile(r"\b(\d{10}-\d{2}-\d{6})\b")
_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "ul", "ol"}
_CELL_TAGS = {"td", "th"}
_SKIP_TAGS = {"script", "style", "head", "title"}


class EdgarError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FilingRef:
    ticker: str
    cik: int
    accession: str
    primary_document: str
    form: str
    report_date: str

    @property
    def file_id(self) -> str:
        return f"sec-{self.ticker.lower()}-10k-{self.accession}"

    @property
    def url(self) -> str:
        return ARCHIVE_URL.format(cik=self.cik, acc_nodash=self.accession.replace("-", ""), doc=self.primary_document)


_TICKER_STOP = {"SEC", "FORM", "THE", "FOR", "FROM", "AND", "LATEST", "MOST", "A", "I", "US", "USG", "EDGAR", "K", "Q", "FY"}


def parse_directive(text: str) -> tuple[str, str | None] | None:
    """Return (TICKER, accession|None) when the prompt asks for a 10-K, else None.

    Grammar (intentionally narrow): the text must contain a ``10-K`` token and one
    upper-case 1-5 letter ticker that is not a common stop word; an optional SEC accession
    number (``##########-##-######``) pins the filing, otherwise the latest 10-K is used.
    """
    if not re.search(r"\b10-?K\b", text):
        return None
    acc = ACCESSION_RE.search(text)
    for m in re.finditer(r"\b([A-Z]{1,5})\b", text):
        if m.group(1) not in _TICKER_STOP:
            return m.group(1), (acc.group(1) if acc else None)
    return None


TABLE_CHUNK_CHARS = 1800  # a table becomes header-prefixed row blocks of at most this size (one DCS paragraph each)


class _TextExtractor(HTMLParser):
    """Prose -> blank-line paragraphs. Tables -> row blocks (rows joined by single newlines, cells by ' | ')
    so a financial table reaches forge-dcs as one paragraph per block with its header row repeated."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._table_depth = 0
        self._rows: list[list[str]] = []
        self._cell: list[str] | None = None
        self._in_caption = False
        self._caption_buf: list[str] = []
        self._table_caption = ""

    # -- prose ------------------------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag == "caption" and self._table_depth == 1:
            self._in_caption = True
            self._caption_buf = []
            return
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
                self._table_caption = ""
            return
        if self._table_depth:
            if tag == "tr":
                self._rows.append([])
            elif tag in _CELL_TAGS:
                self._cell = []
            elif tag == "br" and self._cell is not None:
                self._cell.append(" ")
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n\n" if tag in {"p", "div", "li", "section"} or tag.startswith("h") else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip:
                self._skip -= 1
            return
        if tag == "caption" and self._in_caption:
            self._in_caption = False
            self._table_caption = re.sub(r"\s+", " ", "".join(self._caption_buf)).strip()
            return
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self.parts.append("\n\n" + self._render_table() + "\n\n")
            return
        if self._table_depth:
            if tag in _CELL_TAGS and self._cell is not None:
                txt = re.sub(r"\s+", " ", "".join(self._cell)).strip()
                if self._rows:
                    # Keep empty cells so column indices match the HTML grid (leading row-label column is often blank).
                    self._rows[-1].append(txt)
                self._cell = None
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_caption:
            self._caption_buf.append(data)
            return
        if self._table_depth:
            if self._cell is not None:
                self._cell.append(data)
            return
        self.parts.append(data)

    # -- tables -----------------------------------------------------------------------------
    def _render_table(self) -> str:
        cell_rows: list[list[str]] = []
        for cells in self._rows:
            merged: list[str] = []
            for c in cells:
                if merged and (c in {")", "%", ")%"} or merged[-1] in {"$", "(", "$("}):
                    merged[-1] = (merged[-1] + c).replace("$ ", "$")
                else:
                    merged.append(c)
            merged = [re.sub(r"\s+", " ", m).strip() for m in merged]
            if any(c for c in merged):
                cell_rows.append(merged)
        if not cell_rows:
            return ""

        prefix_parts: list[str] = []
        if self._table_caption:
            prefix_parts.append(self._table_caption)

        hdr_idx, col_labels, unit_note, data_start = _table_header_bundle(cell_rows)
        if unit_note:
            prefix_parts.append(unit_note)
        prefix = "; ".join(prefix_parts) if prefix_parts else ""

        bound_lines = _bind_table_rows(cell_rows, hdr_idx, col_labels, data_start)
        if not bound_lines:
            rows = [" | ".join(r) for r in cell_rows]
            header = rows[0] if len(rows) > 1 and not re.search(r"\d{2,}", rows[0]) else ""
            blocks: list[str] = []
            cur: list[str] = []
            if prefix:
                cur.append(prefix)
            if header:
                cur.append(header)
            cur_len = sum(len(x) + 1 for x in cur)
            iter_rows = rows[1:] if header else rows
            for r in iter_rows:
                if cur and cur_len + len(r) + 1 > TABLE_CHUNK_CHARS and len(cur) > (2 if prefix and header else 1):
                    blocks.append("\n".join(cur))
                    cur = []
                    if prefix:
                        cur.append(prefix)
                    if header:
                        cur.append(header)
                    cur_len = sum(len(x) + 1 for x in cur)
                cur.append(r)
                cur_len += len(r) + 1
            if cur:
                blocks.append("\n".join(cur))
            return "\n\n".join(blocks)

        header_line = "Column | " + " | ".join(col_labels) if col_labels else ""
        blocks2: list[str] = []
        cur2: list[str] = []
        if prefix:
            cur2.append(prefix)
        if header_line:
            cur2.append(header_line)
        cur_len2 = sum(len(x) + 1 for x in cur2)
        for r in bound_lines:
            if cur2 and cur_len2 + len(r) + 1 > TABLE_CHUNK_CHARS and len(cur2) > (2 if prefix and header_line else 1):
                blocks2.append("\n".join(cur2))
                cur2 = []
                if prefix:
                    cur2.append(prefix)
                if header_line:
                    cur2.append(header_line)
                cur_len2 = sum(len(x) + 1 for x in cur2)
            cur2.append(r)
            cur_len2 += len(r) + 1
        if cur2:
            blocks2.append("\n".join(cur2))
        return "\n\n".join(blocks2)


_MONEYISH = re.compile(r"^\$[\d,]+(?:\.\d+)?%?$|^-?\d[\d,]*(?:\.\d+)?$")


def _row_value_cell_ratio(r: list[str]) -> float:
    """Share of non-first cells that look like numeric/money amounts (header rows are low)."""
    if len(r) <= 1:
        return 0.0
    vals = r[1:]
    n = sum(1 for c in vals if _MONEYISH.match(c.strip()) or (c.strip().replace(",", "").replace(".", "", 1).isdigit()))
    return n / max(1, len(vals))


def _table_header_bundle(rows: list[list[str]]) -> tuple[int, list[str], str, int]:
    """Pick header row index, column labels, optional unit line, and first data row index."""
    if not rows:
        return 0, [], "", 0

    best_i, best_score = 0, -1
    scan = min(8, len(rows))
    for i in range(scan):
        r = rows[i]
        joined = " ".join(r).lower()
        score = 0
        for k in ("year ended", "jan ", "feb ", "mar ", "apr ", "$change", "%change", "change", "fiscal"):
            if k in joined:
                score += 2
        if any(re.search(r"20\d{2}", c) for c in r):
            score += 2
        if len(r) >= 3:
            score += 1
        # Penalise rows that are mostly amounts (those are data, not headers)
        vr = _row_value_cell_ratio(r)
        score -= int(6 * vr)
        if vr > 0.65:
            score -= 5
        if score > best_score:
            best_score, best_i = score, i

    unit_note = ""
    hi = best_i if best_score > 0 else 0

    # Prefer a real two-row period header ("Year ended" + dates/$Change) over a later row that looks
    # like a header-scored row but is actually the *second* header line; mis-detecting that as the
    # sole header shifts column labels and binds $Change to the wrong value column.
    for i in range(min(6, max(0, len(rows) - 1))):
        r1, r2 = rows[i], rows[i + 1]
        if not _is_two_row_period_header(r1, r2):
            continue
        if _row_value_cell_ratio(r2) >= 0.5:
            continue
        hi = i
        break

    h1 = list(rows[hi]) if hi < len(rows) else []
    h2 = list(rows[hi + 1]) if hi + 1 < len(rows) else []

    h2_is_data = bool(h2) and _row_value_cell_ratio(h2) >= 0.5
    two_row_period = bool(h2) and not h2_is_data and _is_two_row_period_header(h1, h2)

    col_labels: list[str] = []
    merged_top: list[str] = []

    if h2_is_data:
        # Single header row + first data row immediately below (e.g. Segment | Revenue).
        merged_top = [c.strip() for c in h1]
        start_data = hi + 1
    elif two_row_period:
        # Row1 is often "Year ended" spanners; row2 carries the period / $Change column keys. Do not concatenate.
        col_labels = [c.strip() for c in h2[1:]]
        while col_labels and not col_labels[-1]:
            col_labels.pop()
        merged_top = [""] + col_labels
        start_data = hi + 2
        j1u = " ".join(h1).lower()
        if "million" in j1u or "(in" in j1u:
            for c in h1:
                cl = c.strip().lower()
                if "million" in cl or "(in" in cl:
                    unit_note = c.strip()
                    break
    else:
        merged_top = [c.strip() for c in h1]
        start_data = hi + 1

    if not two_row_period:
        skip_prefix = 0
        while skip_prefix < len(merged_top) and merged_top[skip_prefix] in {"", "—", "-"}:
            skip_prefix += 1
        merged_top = merged_top[skip_prefix:]

        if merged_top:
            fc = merged_top[0].lower()
            if "million" in fc or "(in" in fc or merged_top[0].strip().startswith("$"):
                unit_note = merged_top[0]
                merged_top = merged_top[1:]

        col_labels = merged_top[1:] if len(merged_top) > 1 else merged_top
        col_labels = [c for c in col_labels if c]
        if not col_labels and merged_top:
            col_labels = [c for c in merged_top if c]

    while start_data < len(rows) and _is_unit_or_sparse_row(rows[start_data]):
        if not unit_note:
            unit_note = " ".join(rows[start_data]).strip()
        start_data += 1

    return hi, col_labels, unit_note, start_data


def _is_two_row_period_header(h1: list[str], h2: list[str]) -> bool:
    j1 = " ".join(h1).lower()
    j2 = " ".join(h2).lower()
    has_period_words = "year ended" in j1 or ("year" in j1 and "ended" in j1)
    has_dates_or_change = "jan " in j2 or "dec " in j2 or "$change" in j2 or "%change" in j2
    return bool(has_period_words and has_dates_or_change)


def _is_unit_or_sparse_row(r: list[str]) -> bool:
    j = " ".join(r).lower()
    if "million" in j or ("(in" in j and "million" in j):
        return True
    non_empty = [c for c in r if c.strip()]
    return len(non_empty) <= 1 and not any(re.search(r"\d{2,}", c) for c in non_empty)


def _bind_table_rows(
    cell_rows: list[list[str]],
    hdr_idx: int,
    col_labels: list[str],
    data_start: int,
) -> list[str]:
    if not col_labels or data_start >= len(cell_rows):
        return []

    lines: list[str] = []
    for r in cell_rows[data_start:]:
        if not r:
            continue
        # Rows often start with an empty corner cell; skip leading blanks so the label aligns with headers.
        row = list(r)
        while row and not row[0].strip():
            row.pop(0)
        if not row:
            continue
        label = row[0].strip()
        if not label or _is_unit_or_sparse_row(row):
            continue
        rest = row[1:]
        m = min(len(rest), len(col_labels))
        for j in range(m):
            val = rest[j].strip()
            if not val or val in {"—", "-"}:
                continue
            head = col_labels[j].strip()
            if not head:
                head = f"col{j + 1}"
            lines.append(f"{label} | {head}: {val}")
    return lines


def html_to_paragraph_text(html: str) -> str:
    """HTML -> plain text, blank-line separated paragraphs, NBSP/zero-width stripped, ASCII-safe spaces."""
    ex = _TextExtractor()
    ex.feed(html)
    ex.close()
    raw = "".join(ex.parts)
    raw = raw.replace("\xa0", " ").replace("\u200b", "").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip(" |") for ln in raw.split("\n")]
    out: list[str] = []
    blank = True
    for ln in lines:
        if not ln:
            if not blank:
                out.append("")
            blank = True
            continue
        out.append(ln)
        blank = False
    text = "\n".join(out).strip() + "\n"
    # collapse 3+ newlines to a single blank line
    return re.sub(r"\n{3,}", "\n\n", text)


async def resolve_filing(client: httpx.AsyncClient, ticker: str, accession: str | None, *, user_agent: str) -> FilingRef:
    h = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    try:
        tickers = (await client.get(TICKERS_URL, headers=h, timeout=30.0)).raise_for_status().json()
    except (httpx.HTTPError, ValueError) as ex:
        raise EdgarError("EDGAR_UNAVAILABLE", "could not load SEC ticker map") from ex
    cik = None
    for row in tickers.values() if isinstance(tickers, dict) else []:
        if str(row.get("ticker", "")).upper() == ticker.upper():
            cik = int(row["cik_str"])
            break
    if cik is None:
        raise EdgarError("EDGAR_TICKER_UNKNOWN", f"ticker {ticker} not in SEC map")
    try:
        sub = (await client.get(SUBMISSIONS_URL.format(cik=cik), headers=h, timeout=30.0)).raise_for_status().json()
    except (httpx.HTTPError, ValueError) as ex:
        raise EdgarError("EDGAR_UNAVAILABLE", "could not load SEC submissions") from ex
    recent = sub.get("filings", {}).get("recent", {})
    forms, accs, docs, dates = (recent.get(k, []) for k in ("form", "accessionNumber", "primaryDocument", "reportDate"))
    for form, acc, doc, rd in zip(forms, accs, docs, dates):
        if form != "10-K":
            continue
        if accession and acc != accession:
            continue
        return FilingRef(ticker.upper(), cik, acc, doc, form, rd)
    raise EdgarError("EDGAR_FILING_NOT_FOUND", f"no 10-K for {ticker}" + (f" accession {accession}" if accession else ""))


async def fetch_filing_text(client: httpx.AsyncClient, ref: FilingRef, *, user_agent: str, cache_dir: Path | None) -> bytes:
    cache = (cache_dir / f"{ref.file_id}.html") if cache_dir else None
    if cache and cache.is_file():
        html = cache.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            r = await client.get(ref.url, headers={"User-Agent": user_agent}, timeout=90.0)
            r.raise_for_status()
        except httpx.HTTPError as ex:
            raise EdgarError("EDGAR_UNAVAILABLE", "could not download primary document") from ex
        html = r.text
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(html, encoding="utf-8")
    text = html_to_paragraph_text(html)
    return text.encode("utf-8")


def text_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def filing_meta(ref: FilingRef, data: bytes) -> dict[str, Any]:
    return {
        "ticker": ref.ticker,
        "cik": ref.cik,
        "accession": ref.accession,
        "form": ref.form,
        "report_date": ref.report_date,
        "primary_document": ref.primary_document,
        "url": ref.url,
        "text_bytes": len(data),
        "text_sha256": text_digest(data),
    }


__all__ = [
    "EdgarError",
    "FilingRef",
    "parse_directive",
    "html_to_paragraph_text",
    "resolve_filing",
    "fetch_filing_text",
    "filing_meta",
    "json",
]
