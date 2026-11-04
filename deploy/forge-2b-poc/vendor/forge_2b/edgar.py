"""SEC EDGAR resolver for the forge-2b graph executor.

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

    # -- prose ------------------------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
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
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self.parts.append("\n\n" + self._render_table() + "\n\n")
            return
        if self._table_depth:
            if tag in _CELL_TAGS and self._cell is not None:
                txt = re.sub(r"\s+", " ", "".join(self._cell)).strip()
                if self._rows and txt:
                    self._rows[-1].append(txt)
                self._cell = None
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._table_depth:
            if self._cell is not None:
                self._cell.append(data)
            return
        self.parts.append(data)

    # -- tables -----------------------------------------------------------------------------
    def _render_table(self) -> str:
        rows = []
        for cells in self._rows:
            # EDGAR puts "$" and ")" in their own cells; glue them to the number
            merged: list[str] = []
            for c in cells:
                if merged and (c in {")", "%", ")%"} or merged[-1] in {"$", "(", "$("}):
                    merged[-1] = (merged[-1] + c).replace("$ ", "$")
                else:
                    merged.append(c)
            line = " | ".join(merged).strip(" |")
            if line:
                rows.append(line)
        if not rows:
            return ""
        header = rows[0] if len(rows) > 1 and not re.search(r"\d{2,}", rows[0]) else ""
        blocks: list[str] = []
        cur: list[str] = [header] if header else []
        cur_len = len(header)
        for r in rows[1:] if header else rows:
            if cur and cur_len + len(r) + 1 > TABLE_CHUNK_CHARS and len(cur) > (1 if header else 0):
                blocks.append("\n".join(cur))
                cur = [header] if header else []
                cur_len = len(header)
            cur.append(r)
            cur_len += len(r) + 1
        if cur and (len(cur) > 1 or not header):
            blocks.append("\n".join(cur))
        return "\n\n".join(blocks)


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
