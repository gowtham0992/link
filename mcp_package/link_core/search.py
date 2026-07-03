"""Shared search indexing and ranking helpers for Link."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
try:
    import sqlite3
except Exception:  # pragma: no cover - depends on the host Python build
    sqlite3 = None  # type: ignore[assignment]
from typing import Any


def normalized_search_text(value: object) -> str:
    """Normalize punctuation differences so natural queries match page slugs."""
    text = str(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def search_words(value: object) -> set[str]:
    return {word for word in re.split(r"\W+", normalized_search_text(value)) if len(word) >= 3}


def _search_terms(value: object) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for word in re.split(r"\W+", normalized_search_text(value)):
        if len(word) < 3 or word in seen:
            continue
        seen.add(word)
        terms.append(word)
    return terms


def _populate_fts(conn: Any, pages: list[dict[str, Any]], fulltext: dict[str, str]) -> None:
    conn.execute("CREATE VIRTUAL TABLE page_fts USING fts5(name UNINDEXED, title, metadata, body)")
    rows = []
    for page in pages:
        stem = str(page["name"]).lower()
        metadata = " ".join([
            stem,
            str(page.get("type") or ""),
            str(page.get("category") or ""),
            str(page.get("tldr") or ""),
            " ".join(str(alias) for alias in page.get("aliases", [])),
            " ".join(str(tag) for tag in page.get("tags", [])),
        ])
        rows.append((stem, str(page.get("title") or ""), metadata, fulltext.get(stem, "")))
    conn.executemany("INSERT INTO page_fts(name, title, metadata, body) VALUES (?, ?, ?, ?)", rows)


def _signature_payload(signatures: list[dict[str, Any]] | None) -> str:
    return json.dumps(signatures or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _open_persistent_fts(db_path: Path, signature_payload: str) -> "_FtsIndex | None":
    if not db_path.exists():
        return None
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT value FROM link_fts_meta WHERE key = 'page_signatures'").fetchone()
        if not row or str(row[0]) != signature_payload:
            conn.close()
            return None
        conn.execute("SELECT name FROM page_fts LIMIT 1").fetchall()
        return _FtsIndex(conn, persistent=True, reused=True, path=str(db_path))
    except Exception:
        if conn is not None:
            conn.close()
        return None


def _build_persistent_fts(
    pages: list[dict[str, Any]],
    fulltext: dict[str, str],
    db_path: Path,
    signature_payload: str,
) -> "_FtsIndex | None":
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_name(f"{db_path.name}.tmp")
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except OSError:
        return None
    conn = None
    try:
        conn = sqlite3.connect(str(tmp_path))
        _populate_fts(conn, pages, fulltext)
        conn.execute("CREATE TABLE link_fts_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO link_fts_meta(key, value) VALUES ('page_signatures', ?)",
            (signature_payload,),
        )
        conn.commit()
        conn.close()
        conn = None
        os.replace(tmp_path, db_path)
        conn = sqlite3.connect(str(db_path))
        return _FtsIndex(conn, persistent=True, reused=False, path=str(db_path))
    except Exception:
        if conn is not None:
            conn.close()
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        return None


def build_fts_index(
    pages: list[dict[str, Any]],
    fulltext: dict[str, str],
    *,
    db_path: Path | None = None,
    signatures: list[dict[str, Any]] | None = None,
) -> Any | None:
    """Build an optional in-memory SQLite FTS index.

    Markdown remains the source of truth. This index is derived, local, and
    rebuilt with the normal wiki cache. When ``db_path`` is provided, Link uses
    an on-disk sidecar keyed by page signatures so cold starts can reuse the FTS
    table instead of rebuilding it. Hosts without sqlite/FTS fall back to the
    token index.
    """
    if sqlite3 is None or not pages:
        return None
    if db_path is not None:
        payload = _signature_payload(signatures)
        persistent = _open_persistent_fts(db_path, payload)
        if persistent is not None:
            return persistent
        persistent = _build_persistent_fts(pages, fulltext, db_path, payload)
        if persistent is not None:
            return persistent
    conn = None
    try:
        conn = sqlite3.connect(":memory:")
        _populate_fts(conn, pages, fulltext)
        return _FtsIndex(conn)
    except Exception:
        if conn is not None:
            conn.close()
        return None


def _fts_expr(terms: list[str], operator: str) -> str:
    return f" {operator} ".join(f'"{term}"' for term in terms)


class _FtsIndex:
    def __init__(
        self,
        conn: Any,
        *,
        persistent: bool = False,
        reused: bool = False,
        path: str = "",
    ) -> None:
        self._conn = conn
        self.persistent = persistent
        self.reused = reused
        self.path = path

    def info(self) -> dict[str, object]:
        return {
            "available": True,
            "persistent": self.persistent,
            "reused": self.reused,
            "path": self.path,
        }

    def search(self, query: str, limit: int) -> list[str]:
        terms = _search_terms(query)
        if not terms:
            return []
        expressions = [_fts_expr(terms, "AND")]
        if len(terms) > 1:
            expressions.append(_fts_expr(terms, "OR"))
        for expression in expressions:
            try:
                rows = self._conn.execute(
                    "SELECT name FROM page_fts WHERE page_fts MATCH ? ORDER BY bm25(page_fts) LIMIT ?",
                    (expression, max(1, limit)),
                ).fetchall()
            except Exception:
                continue
            names = [str(row[0]) for row in rows]
            if names:
                return names
        return []

    def close(self) -> None:
        conn = self._conn
        if conn is None:
            return
        self._conn = None
        conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _fts_candidates(cache: dict[str, Any], query: str, limit: int) -> list[str]:
    index = cache.get("fts_index")
    if not isinstance(index, _FtsIndex):
        return []
    return index.search(query, limit)


def _exact_search_candidates(q_lower: str, q_normalized: str, pages: list[dict[str, Any]]) -> set[str]:
    candidates: set[str] = set()
    for page in pages:
        stem = str(page.get("name") or "").lower()
        if not stem:
            continue
        title = str(page.get("title") or "")
        if q_lower == stem or (q_normalized and q_normalized == normalized_search_text(stem)):
            candidates.add(stem)
            continue
        if q_lower in title.lower() or (q_normalized and q_normalized in normalized_search_text(title)):
            candidates.add(stem)
            continue
        aliases = page.get("aliases", [])
        tags = page.get("tags", [])
        tldr = str(page.get("tldr") or "")
        if any(q_lower in str(alias).lower() or (q_normalized and q_normalized in normalized_search_text(alias)) for alias in aliases):
            candidates.add(stem)
            continue
        if any(q_lower in str(tag).lower() or (q_normalized and q_normalized in normalized_search_text(tag)) for tag in tags):
            candidates.add(stem)
            continue
        if q_lower in tldr.lower() or (q_normalized and q_normalized in normalized_search_text(tldr)):
            candidates.add(stem)
    return candidates


def close_wiki_cache(cache: dict[str, Any]) -> None:
    index = cache.get("fts_index") if isinstance(cache, dict) else None
    close = getattr(index, "close", None)
    if callable(close):
        close()
    if isinstance(cache, dict):
        cache["fts_index"] = None


def search_pages(query: str, cache: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    q_lower = q.lower()
    q_normalized = normalized_search_text(q)
    query_tokens = [token for token in re.split(r"\W+", q_lower) if len(token) >= 3]
    pages = cache["pages"]
    page_map = cache["page_map"]
    token_index = cache["token_index"]
    meta_token_index = cache["meta_token_index"]
    fulltext = cache["fulltext"]
    normalized_fulltext = cache.get("normalized_fulltext", {})
    text_words_index = cache.get("text_words_index", {})
    meta_words_index = cache.get("meta_words_index", {})
    snippet_index = cache["snippet_index"]

    is_single_token = bool(re.match(r"^\w+$", q_lower))
    if is_single_token and q_lower in token_index:
        candidates = token_index[q_lower] | meta_token_index.get(q_lower, set())
    elif query_tokens:
        token_sets = [
            token_index.get(token, set()) | meta_token_index.get(token, set())
            for token in query_tokens
            if token in token_index or token in meta_token_index
        ]
        if token_sets:
            intersection = set.intersection(*token_sets)
            candidates = intersection if intersection else set.union(*token_sets)
        else:
            candidates = {page["name"].lower() for page in pages}
    else:
        candidates = {page["name"].lower() for page in pages}

    candidate_cap = max(limit * 25, 200)
    fts_candidates = _fts_candidates(cache, q, limit=candidate_cap)
    if fts_candidates:
        fts_set = set(fts_candidates)
        if len(candidates) > candidate_cap:
            candidates = fts_set | _exact_search_candidates(q_lower, q_normalized, pages)
        else:
            candidates = candidates | fts_set

    scored: list[tuple[int, dict[str, Any]]] = []
    for stem in candidates:
        page = page_map.get(stem)
        if not page:
            continue
        score = 0
        title_normalized = normalized_search_text(page["title"])
        stem_normalized = normalized_search_text(stem)
        aliases = page.get("aliases", [])
        tags = page.get("tags", [])
        tldr = page.get("tldr", "")
        text_lower = fulltext.get(stem, "")
        meta_words = meta_words_index.get(stem)
        if meta_words is None:
            meta_words = search_words(" ".join([
                str(page["title"]),
                stem,
                str(tldr),
                " ".join(str(alias) for alias in aliases),
                " ".join(str(tag) for tag in tags),
            ]))

        if q_lower in str(page["title"]).lower() or (q_normalized and q_normalized in title_normalized):
            score += 10
        if q_lower == stem or (q_normalized and q_normalized == stem_normalized):
            score += 20
        if any(q_lower in alias or (q_normalized and q_normalized in normalized_search_text(alias)) for alias in aliases):
            score += 8
        if any(q_lower in str(tag).lower() or (q_normalized and q_normalized in normalized_search_text(tag)) for tag in tags):
            score += 5
        if q_lower in str(tldr).lower() or (q_normalized and q_normalized in normalized_search_text(tldr)):
            score += 3
        text_normalized = normalized_fulltext.get(stem, "")
        if text_lower and (q_lower in text_lower or (q_normalized and q_normalized in text_normalized)):
            score += 2
        if query_tokens and all(token in meta_words for token in query_tokens):
            score += 6
        elif query_tokens and any(token in meta_words for token in query_tokens):
            score += 1
        if query_tokens and text_normalized:
            text_words = text_words_index.get(stem)
            if text_words is None:
                text_words = search_words(text_normalized)
            if all(token in text_words for token in query_tokens):
                score += 2
        if score > 0:
            scored.append((score, {**page, "score": score, "snippet": snippet_index.get(stem, "")}))

    scored.sort(key=lambda item: (-item[0], str(item[1]["title"]).lower()))
    return [record for _, record in scored[:limit]]
