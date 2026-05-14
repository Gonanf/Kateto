"""
Data collection module for the trainer fine-tuning pipeline.

Provides 6 collector functions that read raw data sources and return
standardized list[dict] with schema: {text, label, source, metadata}.

Each collector is independently testable and handles edge cases
(empty files, corrupt JSON, missing sources) gracefully.
"""

import csv
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Standard schema keys ──────────────────────────────────────────────
TEXT = "text"
LABEL = "label"
SOURCE = "source"
METADATA = "metadata"

# ── Source names ──────────────────────────────────────────────────────
SOURCE_CONVOS = "convos"
SOURCE_TRAINING = "training"
SOURCE_CLASSIFIER_HISTORY = "classifier_history"
SOURCE_BLOGS = "blogs"
SOURCE_XAVIER = "xavier"
SOURCE_CLASSIFIER_CSV = "classifier_csv"

# ── Label names ───────────────────────────────────────────────────────
LABEL_USER_INPUT = "user_input"
LABEL_TALKER_RESPONSE = "talker_response"
LABEL_THINKER_OUTPUT = "thinker_output"
LABEL_USER_BLOG = "user_blog"
LABEL_XAVIER_QUOTE = "xavier_quote"
LABEL_NON_XAVIER_DIALOGUE = "non_xavier_dialogue"


# ══════════════════════════════════════════════════════════════════════
# Helper
# ══════════════════════════════════════════════════════════════════════


def _record(
    text: str, label: str, source: str, metadata: dict | None = None
) -> dict[str, Any]:
    """Build a standardised record dict."""
    return {
        TEXT: text,
        LABEL: label,
        SOURCE: source,
        METADATA: metadata or {},
    }


def _read_path(path: str | Path) -> Path:
    """Resolve to an absolute Path."""
    return Path(path).resolve()


def _iter_json_lines(path: Path) -> list[dict]:
    """Load a JSON file that may have non-JSON prefix lines.

    The OpenCode session exporter sometimes prepends log lines before
    the actual JSON payload. Strategy: find the first '{' and parse from
    there.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    start = raw.find("{")
    if start == -1:
        # Try parsing as a bare array
        start = raw.find("[")
        if start == -1:
            logger.warning("No JSON object/array found in %s", path)
            return []
        raw = raw[start:]
    else:
        raw = raw[start:]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON in %s: %s", path, exc)
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    logger.warning("Unexpected JSON structure in %s (type=%s)", path, type(data).__name__)
    return []


# ══════════════════════════════════════════════════════════════════════
# 1. collect_from_convos — OpenCode session exports
# ══════════════════════════════════════════════════════════════════════


def collect_from_convos(path: str | Path) -> list[dict[str, Any]]:
    """Parse OpenCode session JSON files.

    Handles non-standard format: files have log lines before the JSON
    starts (e.g. ``[opencode-llama-cpp]`` lines).

    For each message in the session:
    - ``role == "user"`` messages → label = ``"user_input"``
    - ``role == "assistant"`` text parts → label = ``"talker_response"``
    - ``role == "assistant"`` reasoning parts → label = ``"thinker_output"``
    """
    p = _read_path(path)
    if not p.exists():
        logger.warning("Convos path does not exist: %s", p)
        return []

    records: list[dict[str, Any]] = []

    if p.is_dir():
        files = sorted(p.glob("*.json"))
    else:
        files = [p]

    for fpath in files:
        session_data = _iter_json_lines(fpath)
        if not session_data:
            continue

        # The top-level could be the session wrapper (if single dict returned)
        if isinstance(session_data, list) and len(session_data) == 1 and isinstance(session_data[0], dict):
            data = session_data[0]
        else:
            data = session_data[0] if session_data else {}

        session_info = data.get("info", {})
        title = session_info.get("title", "")

        messages = data.get("messages", [])
        if not isinstance(messages, list):
            continue

        for msg in messages:
            info = msg.get("info", {})
            role = info.get("role", "")
            model_info = info.get("model", {}) or {}
            model_id = model_info.get("modelID", "")
            provider = model_info.get("providerID", "")
            agent = info.get("agent", "")
            parts = msg.get("parts", [])
            if not isinstance(parts, list):
                continue

            metadata_base: dict[str, Any] = {
                "session_id": session_info.get("id", ""),
                "session_title": title,
                "message_id": info.get("id", ""),
            }
            if agent:
                metadata_base["agent"] = agent
            if model_id:
                metadata_base["model"] = model_id
            if provider:
                metadata_base["provider"] = provider

            for part in parts:
                ptype = part.get("type", "")
                ptext = part.get("text", "")

                if not isinstance(ptext, str) or not ptext.strip():
                    continue

                if role == "user" and ptype == "text":
                    records.append(
                        _record(ptext, LABEL_USER_INPUT, SOURCE_CONVOS, metadata_base)
                    )
                elif role == "assistant" and ptype == "text":
                    records.append(
                        _record(ptext, LABEL_TALKER_RESPONSE, SOURCE_CONVOS, metadata_base)
                    )
                elif role == "assistant" and ptype == "reasoning":
                    records.append(
                        _record(ptext, LABEL_THINKER_OUTPUT, SOURCE_CONVOS, metadata_base)
                    )

    return records


# ══════════════════════════════════════════════════════════════════════
# 2. collect_from_training — existing kateto_dataset files
# ══════════════════════════════════════════════════════════════════════


def collect_from_training(path: str | Path) -> list[dict[str, Any]]:
    """Load existing kateto_dataset_*.json / filtered_*.json files.

    Format: list of ``{input, output}`` or ``{input, output, silence}``.

    - ``silence`` field present:
        ``silence=True`` → label ``"thinker_output"``
        ``silence=False`` → label ``"talker_response"``
    - No ``silence`` field:
        If ``output`` contains ``<think>`` → label ``"thinker_output"``
        Otherwise → label ``"talker_response"``
    - ``filtered_*.json`` files (no ``<think>`` tags expected) → always ``"talker_response"``

    ``text`` field is set to ``input``.
    """
    p = _read_path(path)
    if not p.exists():
        logger.warning("Training path does not exist: %s", p)
        return []

    records: list[dict[str, Any]] = []

    if p.is_dir():
        files = sorted(p.glob("*.json"))
    else:
        files = [p]

    for fpath in files:
        try:
            data = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in training file %s: %s", fpath.name, exc)
            continue

        if not isinstance(data, list):
            logger.warning("Training file %s is not a list (type=%s)", fpath.name, type(data).__name__)
            continue

        is_filtered = "filtered" in fpath.stem.lower()

        for idx, item in enumerate(data):
            inp = item.get("input", "")
            outp = item.get("output", "")
            if not isinstance(inp, str) or not inp.strip():
                continue

            # Determine label
            if "silence" in item:
                silence_val = item["silence"]
                if silence_val is True:
                    label = LABEL_THINKER_OUTPUT
                else:
                    label = LABEL_TALKER_RESPONSE
            elif is_filtered:
                label = LABEL_TALKER_RESPONSE
            elif isinstance(outp, str) and "<think>" in outp:
                label = LABEL_THINKER_OUTPUT
            else:
                label = LABEL_TALKER_RESPONSE

            records.append(
                _record(
                    inp,
                    label,
                    SOURCE_TRAINING,
                    {"filename": fpath.name, "index": idx},
                )
            )

    return records


# ══════════════════════════════════════════════════════════════════════
# 3. collect_from_classifier_history
# ══════════════════════════════════════════════════════════════════════


def collect_from_classifier_history(path: str | Path) -> list[dict[str, Any]]:
    """Load classifier history JSON files.

    Format: list of ``{"text": str, "response": {"label": str, "score": float}}``.

    The ``text`` field maps to ``text`` in the output, and
    ``response.label`` (``"talk"`` / ``"think"``) maps to ``label``.
    """
    p = _read_path(path)
    if not p.exists():
        logger.warning("Classifier history path does not exist: %s", p)
        return []

    records: list[dict[str, Any]] = []

    if p.is_dir():
        files = sorted(p.glob("*.json"))
    else:
        files = [p]

    for fpath in files:
        try:
            data = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in classifier history %s: %s", fpath.name, exc)
            continue

        if not isinstance(data, list):
            logger.warning(
                "Classifier history file %s is not a list (type=%s)",
                fpath.name,
                type(data).__name__,
            )
            continue

        for entry in data:
            text = entry.get("text", "")
            response = entry.get("response")
            if not isinstance(text, str) or not text.strip():
                continue
            if not isinstance(response, dict):
                continue

            label_in = response.get("label", "")
            score = response.get("score")
            meta: dict[str, Any] = {"filename": fpath.name}
            if score is not None:
                meta["confidence_score"] = score

            records.append(
                _record(text, str(label_in), SOURCE_CLASSIFIER_HISTORY, meta)
            )

    return records


# ══════════════════════════════════════════════════════════════════════
# 4. collect_from_blogs — Markdown blog posts
# ══════════════════════════════════════════════════════════════════════


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from markdown text.

    Frontmatter must be between ``---`` delimiters at the start of the
    file. Returns ``(frontmatter_dict, body_text)``.
    """
    stripped = text.lstrip("\ufeff")  # strip BOM if present
    if not stripped.startswith("---"):
        return {}, stripped

    # Find closing ---
    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return {}, stripped

    fm_block = stripped[3:end_idx].strip()
    body = stripped[end_idx + 3 :].strip()

    # Minimal YAML parsing (stdlib only — handle simple k:v pairs)
    frontmatter: dict[str, Any] = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                frontmatter[key] = val

    return frontmatter, body


def collect_from_blogs(path: str | Path) -> list[dict[str, Any]]:
    """Read ``.md`` files as the user's writing style examples.

    - Parses YAML frontmatter if present
    - Extracts main text content (skipping frontmatter)
    - Splits into non-empty paragraphs
    - Labels all as ``"user_blog"``
    """
    p = _read_path(path)
    if not p.exists():
        logger.warning("Blogs path does not exist: %s", p)
        return []

    records: list[dict[str, Any]] = []

    if p.is_dir():
        files = sorted(p.glob("*.md"))
    else:
        files = [p] if p.suffix == ".md" else []

    for fpath in files:
        try:
            raw_text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read blog file %s: %s", fpath.name, exc)
            continue

        fm, body = _parse_frontmatter(raw_text)
        title = fm.get("title", "")

        # Split into non-empty paragraphs
        paragraphs = [para.strip() for para in body.split("\n\n") if para.strip()]

        meta: dict[str, Any] = {"filename": fpath.name}
        if title:
            meta["title"] = title

        for para in paragraphs:
            records.append(
                _record(para, LABEL_USER_BLOG, SOURCE_BLOGS, meta)
            )

    return records


# ══════════════════════════════════════════════════════════════════════
# 5. collect_xavier_quotes — Xavier Wikiquote HTML
# ══════════════════════════════════════════════════════════════════════


class _XavierHTMLParser(HTMLParser):
    """Minimal HTML parser to extract Xavier Wikiquote dialogue lines.

    Targets the pattern ``<dd><b>Speaker:</b> text</dd>`` inside
    ``<dl>`` blocks, with episode/season info in ``<h3>`` headers.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self._current_section = ""
        self._in_dd = False
        self._in_b = False
        self._buffer: list[str] = []
        self._speaker = ""
        self._collect_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h3":
            self._in_dd = False
            self._current_section = ""
        elif tag == "dd":
            self._in_dd = True
            self._buffer = []
            self._speaker = ""
        elif tag == "b" and self._in_dd:
            self._in_b = True
            self._buffer = []
            self._collect_text = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "b" and self._in_b:
            self._speaker = "".join(self._buffer).strip()
            self._in_b = False
            self._buffer = []
            self._collect_text = False
        elif tag == "dd" and self._in_dd:
            dialogue = "".join(self._buffer).strip()
            # Clean up HTML entities and tags inside dialogue
            dialogue = re.sub(r"<[^>]+>", "", dialogue)
            dialogue = dialogue.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            dialogue = dialogue.replace("&quot;", '"').replace("&#39;", "'")
            dialogue = re.sub(r"\s+", " ", dialogue).strip()

            if self._speaker and dialogue:
                # Normalise speaker name (strip trailing colon that Wikiquote includes)
                speaker_name = self._speaker.rstrip(":")
                is_xavier = speaker_name.lower() == "xavier"

                label = LABEL_XAVIER_QUOTE if is_xavier else LABEL_NON_XAVIER_DIALOGUE
                self.records.append(
                    _record(
                        dialogue,
                        label,
                        SOURCE_XAVIER,
                        {
                            "speaker": speaker_name,
                            "section": self._current_section,
                        },
                    )
                )

            self._in_dd = False
            self._buffer = []
            self._speaker = ""
        elif tag == "h3" and self._current_section:
            # Section header ended — keep current_section as is for following dds
            pass

    def handle_data(self, data: str) -> None:
        if self._collect_text and self._in_b:
            self._buffer.append(data)
        elif self._in_dd and not self._in_b:
            self._buffer.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._in_dd:
            char = {
                "amp": "&",
                "lt": "<",
                "gt": ">",
                "quot": '"',
                "apos": "'",
            }.get(name, f"&{name};")
            self._buffer.append(char)


def collect_xavier_quotes(html_path: str | Path) -> list[dict[str, Any]]:
    """Parse Xavier Wikiquote HTML and extract dialogue lines.

    Uses ``html.parser.HTMLParser`` from stdlib (no BeautifulSoup needed).

    Each Xavier line → label ``"xavier_quote"``
    Other speaker lines → label ``"non_xavier_dialogue"``
    """
    p = _read_path(html_path)
    if not p.exists():
        logger.warning("Xavier HTML file does not exist: %s", p)
        return []

    try:
        html_content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read Xavier HTML file %s: %s", p, exc)
        return []

    parser = _XavierHTMLParser()
    try:
        parser.feed(html_content)
    except Exception as exc:
        logger.warning("Error parsing Xavier HTML: %s", exc)
        return []

    return parser.records


# ══════════════════════════════════════════════════════════════════════
# 6. collect_classifier_csv — CSV with text,label
# ══════════════════════════════════════════════════════════════════════


def collect_classifier_csv(csv_path: str | Path) -> list[dict[str, Any]]:
    """Load a CSV file with ``text,label`` columns.

    Each row produces a record with label matching the CSV label and
    text from the CSV text column.
    """
    p = _read_path(csv_path)
    if not p.exists():
        logger.warning("Classifier CSV path does not exist: %s", p)
        return []

    records: list[dict[str, Any]] = []

    if p.is_dir():
        files = sorted(p.glob("*.csv"))
    else:
        files = [p]

    for fpath in files:
        try:
            with fpath.open(encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    text = row.get("text", "")
                    label = row.get("label", "")
                    if not text.strip() or not label.strip():
                        continue
                    records.append(
                        _record(
                            text.strip(),
                            label.strip(),
                            SOURCE_CLASSIFIER_CSV,
                            {"filename": fpath.name},
                        )
                    )
        except Exception as exc:
            logger.warning("Error reading CSV %s: %s", fpath.name, exc)
            continue

    return records


# ══════════════════════════════════════════════════════════════════════
# Aggregate
# ══════════════════════════════════════════════════════════════════════


def collect_all(raw_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Run all collectors and return ``{source_name: items}`` dict.

    ``raw_dir`` should point to ``data/raw/`` (the directory containing
    ``convos/``, ``training/``, ``blogs/``, ``classifier/``, and
    ``xavier.html``).
    """
    raw = _read_path(raw_dir)
    if not raw.is_dir():
        logger.warning("raw_dir is not a directory: %s", raw)
        return {}

    results: dict[str, list[dict[str, Any]]] = {}

    # 1. Convos
    convos_path = raw / "convos"
    results[SOURCE_CONVOS] = collect_from_convos(convos_path)

    # 2. Training
    training_path = raw / "training"
    results[SOURCE_TRAINING] = collect_from_training(training_path)

    # 3. Classifier history
    history_path = raw / "classifier" / "history"
    results[SOURCE_CLASSIFIER_HISTORY] = collect_from_classifier_history(history_path)

    # 4. Blogs
    blogs_path = raw / "blogs"
    results[SOURCE_BLOGS] = collect_from_blogs(blogs_path)

    # 5. Xavier quotes
    xavier_path = raw / "xavier.html"
    results[SOURCE_XAVIER] = collect_xavier_quotes(xavier_path)

    # 6. Classifier CSV
    csv_path = raw / "classifier" / "coarse_grained.csv"
    results[SOURCE_CLASSIFIER_CSV] = collect_classifier_csv(csv_path)

    # Log summary
    for src, items in results.items():
        logger.info("Collected %d items from %s", len(items), src)

    return results
