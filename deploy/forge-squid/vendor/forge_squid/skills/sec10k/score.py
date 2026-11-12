"""Multi-dimensional composite score (0–100), deterministic."""
from __future__ import annotations

import re
from typing import Any

_NEG = re.compile(r"\b(decline|decrease|down|fall|adverse|loss|risk|restrict|ban)\b", re.I)


def score_observation(obs: dict[str, Any], verification: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    impact = int(obs.get("impact") or 3)
    materiality = min(100, max(0, impact * 20))

    text = str(obs.get("text") or "")
    novelty = 40
    if "guidance" in text.lower() or str(obs.get("statement_mode")) == "guidance":
        novelty += 15
    low = text.lower()
    if "data center" in low or "segment" in low or "geographic" in low:
        novelty += 10

    quantified = 80 if (obs.get("values") or []) else 25

    vstat = str(verification.get("status") or "UNVERIFIED")
    verified = {"VERIFIED": 100, "UNVERIFIED": 35, "CONTRADICTED": 0}.get(vstat, 35)

    sentiment = 50
    if _NEG.search(text):
        sentiment -= 25

    w_mat = float(weights.get("materiality", 0.25))
    w_nov = float(weights.get("novelty", 0.15))
    w_qu = float(weights.get("quantified", 0.15))
    w_ver = float(weights.get("verified", 0.30))
    w_sent = float(weights.get("sentiment", 0.15))
    wsum = w_mat + w_nov + w_qu + w_ver + w_sent
    if wsum <= 0:
        wsum = 1.0

    composite = (
        materiality * w_mat + novelty * w_nov + quantified * w_qu + verified * w_ver + sentiment * w_sent
    ) / wsum
    composite = int(round(max(0, min(100, composite))))

    return {
        "composite": composite,
        "dimensions": {
            "materiality": int(materiality),
            "novelty": int(novelty),
            "quantified": int(quantified),
            "verified": int(verified),
            "sentiment": int(sentiment),
        },
    }
