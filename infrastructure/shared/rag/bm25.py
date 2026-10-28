"""Small lexical retrieval engine shared by schema and API retrieval."""

from collections import Counter
import math
import re

STOP_WORDS = set("a an the and or of to in on for is are be by with as from this that it then when given".split())


def tokenize(text: str) -> list[str]:
    """Split identifiers and text into lowercase search tokens, dropping common stop words."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return [word for word in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()) if word not in STOP_WORDS]


def rank(query: str, documents: dict[str, str], top_k: int) -> list[dict]:
    """Score the current document inventory with BM25 and return the top positive matches in stable order."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not documents:
        return []
    counts = {symbol: Counter(tokenize(text)) for symbol, text in documents.items()}
    frequencies = Counter(term for count in counts.values() for term in count)
    average_length = sum(sum(count.values()) for count in counts.values()) / len(counts)
    matches = []
    for symbol, count in counts.items():
        score = 0.0
        for term in set(tokenize(query)):
            frequency = count[term]
            if frequency:
                inverse_frequency = math.log(1 + (len(counts) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                normalization = 1.2 * (0.25 + 0.75 * sum(count.values()) / max(average_length, 1))
                score += inverse_frequency * frequency * 2.2 / (frequency + normalization)
        if score > 0:
            matches.append({"symbol": symbol, "score": round(score, 4)})
    return sorted(matches, key=lambda match: (-match["score"], match["symbol"]))[:top_k]
