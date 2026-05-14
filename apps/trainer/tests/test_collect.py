"""Tests for trainer data collection module."""

import json
import csv
from pathlib import Path

import pytest
from trainer.collect import (
    _iter_json_lines,
    _parse_frontmatter,
    collect_from_convos,
    collect_from_training,
    collect_from_classifier_history,
    collect_from_blogs,
    collect_xavier_quotes,
    collect_classifier_csv,
    collect_all,
)


# ── _iter_json_lines ──────────────────────────────────────────────────────────


class TestIterJsonLines:
    """Unit tests for the _iter_json_lines helper."""

    def test_pure_json_object(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        data = {"key": "value", "nested": {"a": 1}}
        f.write_text(json.dumps(data))
        result = _iter_json_lines(f)
        assert result == [data]

    def test_with_log_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("[opencode-llama-cpp] {\"messages\": []}\n")
        result = _iter_json_lines(f)
        assert result == [{"messages": []}]

    def test_bare_object_wrapped_in_list(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        result = _iter_json_lines(f)
        assert result == [{"key": "value"}]

    def test_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"truncated": true, "missing": end')
        result = _iter_json_lines(f)
        assert result == []

    def test_no_json_found_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("Just some log lines\nNo JSON here\n")
        result = _iter_json_lines(f)
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("")
        result = _iter_json_lines(f)
        assert result == []

    def test_bare_array_no_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("[1, 2, 3]")
        result = _iter_json_lines(f)
        assert result == [1, 2, 3]


# ── collect_from_convos ───────────────────────────────────────────────────────


class TestCollectFromConvos:
    """OpenCode session export collector."""

    CONVO_TEMPLATE = {
        "info": {"id": "ses_01", "title": "Test Session"},
        "messages": [
            {
                "info": {
                    "id": "msg_01",
                    "role": "user",
                    "model": {"modelID": "test-model", "providerID": "test"},
                },
                "parts": [{"type": "text", "text": "Hello world"}],
            },
            {
                "info": {
                    "id": "msg_02",
                    "role": "assistant",
                    "model": {"modelID": "test-model", "providerID": "test"},
                },
                "parts": [
                    {"type": "text", "text": "Hi there"},
                    {"type": "reasoning", "text": "Let me think..."},
                ],
            },
        ],
    }

    def test_user_and_assistant_messages(self, tmp_path: Path) -> None:
        f = tmp_path / "session.json"
        f.write_text(json.dumps(self.CONVO_TEMPLATE))
        records = collect_from_convos(str(f))
        assert len(records) == 3
        assert records[0]["label"] == "user_input"
        assert records[0]["text"] == "Hello world"
        assert records[1]["label"] == "talker_response"
        assert records[1]["text"] == "Hi there"
        assert records[2]["label"] == "thinker_output"
        assert records[2]["text"] == "Let me think..."

    def test_empty_message_list(self, tmp_path: Path) -> None:
        f = tmp_path / "session.json"
        data = {"info": {"id": "s1"}, "messages": []}
        f.write_text(json.dumps(data))
        assert collect_from_convos(str(f)) == []

    def test_non_list_messages_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "session.json"
        data = {"info": {"id": "s1"}, "messages": "not_a_list"}
        f.write_text(json.dumps(data))
        assert collect_from_convos(str(f)) == []

    def test_missing_file_returns_empty(self) -> None:
        assert collect_from_convos("/nonexistent/path.json") == []

    def test_empty_part_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "session.json"
        data = {
            "info": {"id": "s1"},
            "messages": [
                {
                    "info": {"role": "user"},
                    "parts": [{"type": "text", "text": ""}],
                }
            ],
        }
        f.write_text(json.dumps(data))
        assert collect_from_convos(str(f)) == []

    def test_directory_with_multiple_files(self, tmp_path: Path) -> None:
        d = tmp_path / "convos"
        d.mkdir()
        (d / "a.json").write_text(json.dumps(self.CONVO_TEMPLATE))
        (d / "b.json").write_text(json.dumps(self.CONVO_TEMPLATE))
        records = collect_from_convos(str(d))
        assert len(records) == 6  # 3 from each file


# ── collect_from_training ─────────────────────────────────────────────────────


class TestCollectFromTraining:
    """Training dataset collector."""

    def test_input_output_format(self, tmp_path: Path) -> None:
        f = tmp_path / "kateto_dataset.json"
        data = [
            {"input": "Que hora es?", "output": "Son las tres"},
            {"input": "Como estas?", "output": "Bien, gracias"},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_training(str(f))
        assert len(records) == 2
        assert all(r["label"] == "talker_response" for r in records)
        assert records[0]["text"] == "Que hora es?"

    def test_silence_flag(self, tmp_path: Path) -> None:
        f = tmp_path / "dataset.json"
        data = [
            {"input": "silent", "output": "shh", "silence": True},
            {"input": "vocal", "output": "hello", "silence": False},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_training(str(f))
        assert len(records) == 2
        assert records[0]["label"] == "thinker_output"
        assert records[1]["label"] == "talker_response"

    def test_think_tag_detection(self, tmp_path: Path) -> None:
        f = tmp_path / "dataset.json"
        data = [
            {"input": "deep question", "output": "<think>processing</think>answer"},
            {"input": "simple q", "output": "direct answer"},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_training(str(f))
        assert len(records) == 2
        assert records[0]["label"] == "thinker_output"
        assert records[1]["label"] == "talker_response"

    def test_filtered_file_always_talker(self, tmp_path: Path) -> None:
        f = tmp_path / "filtered_output.json"
        data = [
            {"input": "q1", "output": "<think>reasoning</think>ans"},
            {"input": "q2", "output": "direct"},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_training(str(f))
        # filtered_ prefix means no thinker detection
        assert all(r["label"] == "talker_response" for r in records)

    def test_empty_input_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "dataset.json"
        data = [
            {"input": "", "output": "empty input"},
            {"input": "valid", "output": "good"},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_training(str(f))
        assert len(records) == 1

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json")
        assert collect_from_training(str(f)) == []

    def test_empty_list(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text("[]")
        assert collect_from_training(str(f)) == []

    def test_not_a_list(self, tmp_path: Path) -> None:
        f = tmp_path / "obj.json"
        f.write_text('{"input": "test"}')
        assert collect_from_training(str(f)) == []


# ── collect_from_classifier_history ───────────────────────────────────────────


class TestCollectFromClassifierHistory:
    """Classifier history collector."""

    def test_valid_history(self, tmp_path: Path) -> None:
        f = tmp_path / "history.json"
        data = [
            {"text": "Hola", "response": {"label": "talk", "score": 0.95}},
            {"text": "A ver...", "response": {"label": "think", "score": 0.87}},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_classifier_history(str(f))
        assert len(records) == 2
        assert records[0]["label"] == "talk"
        assert records[0]["text"] == "Hola"
        assert records[0]["metadata"]["confidence_score"] == 0.95
        assert records[1]["label"] == "think"

    def test_empty_array(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text("[]")
        assert collect_from_classifier_history(str(f)) == []

    def test_missing_text_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "history.json"
        data = [
            {"text": "", "response": {"label": "talk"}},
            {"text": "valid", "response": {"label": "think"}},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_classifier_history(str(f))
        assert len(records) == 1

    def test_missing_response_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "history.json"
        data = [
            {"text": "no response"},
            {"text": "valid", "response": {"label": "talk"}},
        ]
        f.write_text(json.dumps(data))
        records = collect_from_classifier_history(str(f))
        assert len(records) == 1

    def test_no_score_in_metadata(self, tmp_path: Path) -> None:
        f = tmp_path / "history.json"
        data = [{"text": "test", "response": {"label": "talk"}}]
        f.write_text(json.dumps(data))
        records = collect_from_classifier_history(str(f))
        assert "confidence_score" not in records[0]["metadata"]

    def test_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{corrupt")
        assert collect_from_classifier_history(str(f)) == []

    def test_not_a_list(self, tmp_path: Path) -> None:
        f = tmp_path / "obj.json"
        f.write_text('{"text": "test"}')
        assert collect_from_classifier_history(str(f)) == []


# ── _parse_frontmatter ────────────────────────────────────────────────────────


class TestParseFrontmatter:
    """Frontmatter parsing helper."""

    def test_with_frontmatter(self) -> None:
        text = "---\ntitle: My Post\ndate: 2024-01-01\n---\n\nBody content"
        fm, body = _parse_frontmatter(text)
        assert fm["title"] == "My Post"
        assert fm["date"] == "2024-01-01"
        assert "Body content" in body

    def test_no_frontmatter(self) -> None:
        text = "# Just a title\n\nSome content"
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_bom_stripped(self) -> None:
        text = "\ufeff---\ntitle: BOM Test\n---\n\nBody"
        fm, body = _parse_frontmatter(text)
        assert fm["title"] == "BOM Test"

    def test_unclosed_frontmatter(self) -> None:
        text = "---\ntitle: Unclosed\n\nBody"
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert "Body" in body

    def test_quoted_values(self) -> None:
        text = '---\ntitle: "My Title"\n---\n\nBody'
        fm, body = _parse_frontmatter(text)
        assert fm["title"] == "My Title"


# ── collect_from_blogs ────────────────────────────────────────────────────────


class TestCollectFromBlogs:
    """Blog markdown collector."""

    def test_blog_with_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "post.md"
        f.write_text("---\ntitle: My Blog\n---\n\nFirst paragraph\n\nSecond paragraph")
        records = collect_from_blogs(str(f))
        assert len(records) == 2
        assert records[0]["label"] == "user_blog"
        assert records[0]["metadata"]["title"] == "My Blog"
        assert "First paragraph" in records[0]["text"]

    def test_blog_no_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "post.md"
        f.write_text("First paragraph\n\nSecond paragraph")
        records = collect_from_blogs(str(f))
        assert len(records) == 2

    def test_non_md_file_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "note.txt"
        f.write_text("Not a blog")
        assert collect_from_blogs(str(f)) == []

    def test_empty_blog_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("")
        records = collect_from_blogs(str(f))
        assert records == []

    def test_directory_with_blogs(self, tmp_path: Path) -> None:
        d = tmp_path / "blogs"
        d.mkdir()
        (d / "a.md").write_text("---\ntitle: A\n---\n\nContent A")
        (d / "b.md").write_text("---\ntitle: B\n---\n\nContent B\n\nMore B")
        records = collect_from_blogs(str(d))
        assert len(records) == 3  # 1 para from a.md, 2 from b.md

    def test_missing_path(self) -> None:
        assert collect_from_blogs("/nonexistent") == []


# ── collect_xavier_quotes ─────────────────────────────────────────────────────


class TestCollectXavierQuotes:
    """Wikiquote HTML parser collector."""

    XAVIER_HTML = """<html>
<body>
<h3>Season 1</h3>
<dl>
<dd><b>Xavier:</b> What doth life?</dd>
<dd><b>Friend:</b> I don't know.</dd>
</dl>
</body>
</html>"""

    def test_extracts_xavier_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "xavier.html"
        f.write_text(self.XAVIER_HTML)
        records = collect_xavier_quotes(str(f))
        assert len(records) == 2
        assert records[0]["label"] == "xavier_quote"
        assert records[0]["text"] == "What doth life?"
        assert records[0]["metadata"]["speaker"] == "Xavier"
        assert records[1]["label"] == "non_xavier_dialogue"

    def test_html_entities_decoded(self, tmp_path: Path) -> None:
        f = tmp_path / "xavier.html"
        f.write_text(
            "<dl><dd><b>Xavier:</b> It&apos;s &amp; that</dd></dl>"
        )
        records = collect_xavier_quotes(str(f))
        assert len(records) == 1
        assert "It's & that" in records[0]["text"]

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.html"
        f.write_text("")
        assert collect_xavier_quotes(str(f)) == []

    def test_missing_file(self) -> None:
        assert collect_xavier_quotes("/nonexistent.html") == []

    def test_no_dl_blocks(self, tmp_path: Path) -> None:
        f = tmp_path / "noquotes.html"
        f.write_text("<html><p>No quotes here</p></html>")
        assert collect_xavier_quotes(str(f)) == []


# ── collect_classifier_csv ────────────────────────────────────────────────────


class TestCollectClassifierCSV:
    """CSV classifier data collector."""

    def test_valid_csv(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("text,label\nHello,talk\nWorld,think\n")
        records = collect_classifier_csv(str(f))
        assert len(records) == 2
        assert records[0]["label"] == "talk"
        assert records[0]["text"] == "Hello"
        assert records[1]["label"] == "think"

    def test_skips_empty_rows(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("text,label\n,talk\nHello,\nValid,think\n")
        records = collect_classifier_csv(str(f))
        assert len(records) == 1

    def test_missing_file(self) -> None:
        assert collect_classifier_csv("/nonexistent.csv") == []

    def test_directory_with_csvs(self, tmp_path: Path) -> None:
        d = tmp_path / "csvs"
        d.mkdir()
        (d / "a.csv").write_text("text,label\nA,talk\n")
        (d / "b.csv").write_text("text,label\nB,think\n")
        records = collect_classifier_csv(str(d))
        assert len(records) == 2

    def test_corrupt_csv_handled(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.csv"
        f.write_text("text,label\n")
        records = collect_classifier_csv(str(f))
        assert records == []


# ── collect_all ───────────────────────────────────────────────────────────────


class TestCollectAll:
    """Aggregate collector."""

    def test_empty_raw_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "raw"
        d.mkdir()
        result = collect_all(str(d))
        assert isinstance(result, dict)
        assert len(result) == 6  # all 6 source keys present
        for key, items in result.items():
            assert items == [], f"{key} should be empty, got {items}"

    def test_non_existent_dir(self) -> None:
        result = collect_all("/nonexistent/raw")
        assert result == {}

    def test_file_instead_of_dir(self, tmp_path: Path) -> None:
        f = tmp_path / "not_a_dir.txt"
        f.write_text("hello")
        result = collect_all(str(f))
        assert result == {}

    def test_partial_data(self, tmp_path: Path) -> None:
        raw = tmp_path / "raw"
        raw.mkdir()
        # Only create convos dir with one file
        convos = raw / "convos"
        convos.mkdir()
        (convos / "session.json").write_text(
            json.dumps({
                "info": {"id": "s1"},
                "messages": [
                    {
                        "info": {"role": "user"},
                        "parts": [{"type": "text", "text": "hi"}],
                    }
                ],
            })
        )
        result = collect_all(str(raw))
        assert len(result["convos"]) == 1
        # Other sources are empty but present
        assert result["training"] == []
        assert result["classifier_history"] == []
        assert result["blogs"] == []
        assert result["xavier"] == []
        assert result["classifier_csv"] == []
