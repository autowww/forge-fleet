"""Curated per-domain alias table for DCE-03 retrieval. Data only; versioned so evaluations can cite it.

Keys are canonical *field / key names* as they appear in configs, CSV headers, code constants and prose; values are
user-vocabulary phrases that mean the same thing. Expansion is symmetric (a canonical key also expands to its
aliases) and Unicode/NFKC-normalized at lookup time. No model, no learned weights.
"""
from __future__ import annotations

import re
import unicodedata

ALIASES_VERSION = "dce.aliases.v1"

ALIASES: dict[str, tuple[str, ...]] = {
    # deployment / runtime configuration
    "replicas": ("replica", "instances", "instance", "copies", "copy", "pods", "pod", "replica count", "how many instances", "scale", "scaled", "running copies", "deployed instances",
                 # de / fr / es / pl / ru / uk
                 "replikate", "replikas", "instanzen", "réplicas", "replicas", "instancias", "repliki", "replik", "replika", "instancji", "реплик", "реплики", "реплика", "экземпляров", "реплік", "репліки", "репліка"),
    "port": ("ports", "listening port", "listen on", "listens on", "tcp port", "endpoint port", "bind", "bound to", "exposed on", "exposed",
             "porta", "puerto", "портом", "порт", "порту"),
    "timeout": ("time out", "timed out", "deadline", "timeout value", "time limit", "wait", "gives up", "give up", "giving up", "wait before failing", "expire", "expires",
                "zeitlimit", "délai", "tiempo de espera", "limit czasu", "таймаут", "тайм-аут"),
    "memory_limit_mb": ("memory limit", "memory", "ram", "mem", "mem limit", "memory cap", "mb"),
    "name": ("service name", "called", "named", "what is it called", "identifier"),
    "health": ("healthcheck", "health check", "health endpoint", "liveness", "readiness", "probe"),
    # ownership / metadata
    "owner": ("owns", "owned by", "owning team", "maintainer", "maintained by", "responsible team", "team", "who owns"),
    "region": ("zone", "location", "datacenter", "data center", "aws region", "cloud region", "where is it hosted", "hosted"),
    "retention_days": ("retention", "retain", "retained", "kept for", "keep data", "how long is data kept", "retention period"),
    "contact": ("email", "e-mail", "reach", "address", "mail", "contact address", "who to contact"),
    # test results (tabular)
    "status": ("result", "results", "outcome", "verdict", "passed", "failed", "skipped", "pass", "fail", "skip", "state"),
    "duration_ms": ("duration", "took", "runtime", "how long", "slow", "slowest", "fastest", "quickest", "longest", "shortest", "time taken", "ms", "milliseconds"),
    "message": ("error message", "reason", "why", "failure message", "details"),
    "test": ("tests", "test case", "test cases", "test name"),
    # docs
    "uptime": ("availability", "sla", "uptime target", "nines"),
    "rollback": ("roll back", "revert", "rollback window", "undo"),
    "sentinel": ("marker", "token", "canary"),
    "requirements": ("requirement", "must", "shall", "needs to", "required"),
    "changelog": ("change log", "release notes", "history", "what changed", "changes", "added", "introduced", "raised", "when was", "which month", "which version", "release date"),
    "version": ("release", "tag", "v"),
    "deployment": ("deploy", "deployed", "rollout", "release train", "production"),
    # code
    "default_port": ("default port", "port constant", "hardcoded port"),
    "timezone": ("time zone", "tz", "zeitzone", "zone horaire", "zona horaria", "strefa czasowa", "часовой пояс", "часовий пояс"),
}

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().strip()


def _index(table: dict[str, tuple[str, ...]]) -> dict[str, set[str]]:
    """phrase (normalized) → set of canonical keys."""
    out: dict[str, set[str]] = {}
    for key, phrases in table.items():
        k = norm(key)
        out.setdefault(k, set()).add(key)
        for p in phrases:
            out.setdefault(norm(p), set()).add(key)
    return out


PHRASE_TO_KEYS = _index(ALIASES)
MAX_PHRASE_WORDS = max(len(p.split()) for p in PHRASE_TO_KEYS)


def expand(query: str, table: dict[str, tuple[str, ...]] | None = None) -> dict[str, list[str]]:
    """Return {canonical_key: [phrases in the query that triggered it]} using longest-match-first n-grams."""
    idx = PHRASE_TO_KEYS if table is None else _index(table)
    words = _WORD_RE.findall(norm(query))
    hits: dict[str, list[str]] = {}
    i = 0
    while i < len(words):
        matched = 0
        for n in range(min(MAX_PHRASE_WORDS, len(words) - i), 0, -1):
            phrase = " ".join(words[i:i + n])
            if phrase in idx:
                for key in sorted(idx[phrase]):
                    hits.setdefault(key, []).append(phrase)
                matched = n
                break
        i += matched or 1
    return hits


def expansions_for_key(key: str, table: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    t = ALIASES if table is None else table
    return [norm(key)] + [norm(p) for p in t.get(key, ())]
