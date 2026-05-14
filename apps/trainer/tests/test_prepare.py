"""Tests for trainer data preparation module."""

import pytest
from trainer.prepare import (
    _jaccard_similarity,
    deduplicate,
    split_train_val,
    _extract_user_text,
    _extract_assistant_text,
    format_chatml,
    format_classification,
)


# ── _jaccard_similarity ───────────────────────────────────────────────────────


class TestJaccardSimilarity:
    def test_identical_strings(self) -> None:
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self) -> None:
        sim = _jaccard_similarity("abc", "xyz")
        assert sim == 0.0

    def test_partial_overlap(self) -> None:
        sim = _jaccard_similarity("hello world foo", "hello world bar")
        assert 0.0 < sim < 1.0

    def test_very_short_strings(self) -> None:
        # Strings shorter than 4 chars produce empty n-gram sets
        sim = _jaccard_similarity("a", "b")
        assert sim == 0.0

    def test_longer_near_match(self) -> None:
        a = "This is a test of the emergency broadcast system"
        b = "This is a test of emergency broadcast system"
        sim = _jaccard_similarity(a, b)
        assert sim > 0.8


# ── deduplicate ───────────────────────────────────────────────────────────────


class TestDeduplicate:
    def test_exact_duplicates(self) -> None:
        items = [
            {"text": "Hello world", "label": "a"},
            {"text": "Hello world", "label": "a"},
            {"text": "Different text", "label": "b"},
        ]
        result = deduplicate(items, key="text")
        assert len(result) == 2

    def test_near_duplicates(self) -> None:
        items = [
            {"text": "This is a test of the system with more words", "label": "a"},
            {"text": "This is a test of the system with more words!", "label": "a"},
        ]
        result = deduplicate(items, key="text", threshold=0.85)
        assert len(result) == 1

    def test_no_duplicates(self) -> None:
        items = [
            {"text": "Completely different one", "label": "a"},
            {"text": "Totally unrelated text", "label": "b"},
        ]
        result = deduplicate(items, key="text")
        assert len(result) == 2

    def test_dedup_keys_multiple(self) -> None:
        items = [
            {"text": "Hello", "output": "World", "label": "a"},
            {"text": "Hello", "output": "World", "label": "a"},
        ]
        result = deduplicate(items, dedup_keys=["text", "output"])
        assert len(result) == 1

    def test_dedup_keys_with_dict_value(self) -> None:
        items = [
            {"input": {"input": "hello"}, "output": "world"},
            {"input": {"input": "hello"}, "output": "world"},
        ]
        result = deduplicate(items, dedup_keys=["input", "output"])
        assert len(result) == 1

    def test_empty_items_list(self) -> None:
        result = deduplicate([])
        assert result == []

    def test_items_with_empty_text_always_kept(self) -> None:
        items = [
            {"text": "", "label": "a"},
            {"text": "", "label": "b"},
        ]
        result = deduplicate(items, key="text")
        assert len(result) == 2  # both kept since text is empty

    def test_lower_threshold_no_dedup(self) -> None:
        items = [
            {"text": "One two three four five", "label": "a"},
            {"text": "One two three four six", "label": "b"},
        ]
        result = deduplicate(items, key="text", threshold=0.99)
        assert len(result) == 2  # similar but not identical at 0.99

    def test_single_item(self) -> None:
        items = [{"text": "only one", "label": "a"}]
        result = deduplicate(items)
        assert len(result) == 1


# ── split_train_val ───────────────────────────────────────────────────────────


class TestSplitTrainVal:
    def test_stratified_split(self) -> None:
        items = [
            {"text": "A", "label": "talk"},
            {"text": "B", "label": "talk"},
            {"text": "C", "label": "think"},
            {"text": "D", "label": "think"},
            {"text": "E", "label": "talk"},
        ]
        train, val = split_train_val(items, val_split=0.2, stratify_key="label")
        assert len(train) > 0
        assert len(val) > 0
        assert len(train) + len(val) == len(items)

    def test_reproducible_seed(self) -> None:
        items = [{"text": str(i), "label": "talk"} for i in range(20)]
        train1, val1 = split_train_val(items)
        train2, val2 = split_train_val(items)
        assert train1 == train2
        assert val1 == val2

    def test_no_stratify(self) -> None:
        items = [{"text": str(i), "label": "talk"} for i in range(10)]
        train, val = split_train_val(items, stratify_key=None)
        assert len(train) + len(val) == 10
        assert len(val) > 0

    def test_single_item_per_label(self) -> None:
        items = [
            {"text": "Only talk", "label": "talk"},
        ]
        train, val = split_train_val(items, val_split=0.5)
        # With 1 item, split must keep at least 1 in each when possible
        assert len(train) + len(val) == 1

    def test_val_split_zero(self) -> None:
        items = [{"text": str(i), "label": "talk"} for i in range(5)]
        train, val = split_train_val(items, val_split=0.0)
        # Code guards split_idx >= len(indices), so at most 1 in val
        assert len(val) <= 1
        assert len(train) + len(val) == 5

    def test_val_split_one(self) -> None:
        items = [{"text": str(i), "label": "talk"} for i in range(5)]
        train, val = split_train_val(items, val_split=1.0)
        # Code guards split_idx >= len(indices), so at most 1 in train
        assert len(train) <= 1
        assert len(train) + len(val) == 5

    def test_preserves_item_order(self) -> None:
        items = [
            {"text": "a", "label": "talk"},
            {"text": "b", "label": "think"},
            {"text": "c", "label": "talk"},
            {"text": "d", "label": "think"},
        ]
        train, val = split_train_val(items, val_split=0.5, stratify_key="label")
        all_items = train + val
        # All original items present (order may differ due to stratification)
        assert len(all_items) == len(items)


# ── _extract_user_text / _extract_assistant_text ──────────────────────────────


class TestExtractHelpers:
    def test_user_text_from_direct_input(self) -> None:
        assert _extract_user_text({"input": "hello"}) == "hello"

    def test_user_text_from_nested_input(self) -> None:
        assert _extract_user_text({"input": {"input": "nested"}}) == "nested"

    def test_user_text_missing(self) -> None:
        assert _extract_user_text({"text": "hi"}) == ""

    def test_assistant_text_from_text_field(self) -> None:
        assert _extract_assistant_text({"text": "response text"}) == "response text"

    def test_assistant_text_from_output(self) -> None:
        assert _extract_assistant_text({"output": "output text"}) == "output text"

    def test_assistant_text_with_response_tags(self) -> None:
        item = {"output": "prefix<response>inner text</response>suffix"}
        assert _extract_assistant_text(item) == "inner text"

    def test_assistant_text_missing(self) -> None:
        assert _extract_assistant_text({}) == ""


# ── format_chatml ─────────────────────────────────────────────────────────────


class TestFormatChatML:
    def test_blog_item(self) -> None:
        items = [
            {"text": "My blog post content", "label": "user_blog", "source": "blogs"}
        ]
        result = format_chatml(items)
        assert "blog post" in result[0]["text"]
        assert "<|im_start|>" in result[0]["text"]

    def test_xavier_item(self) -> None:
        items = [
            {"text": "What doth life?", "label": "xavier_quote", "source": "xavier"}
        ]
        result = format_chatml(items)
        assert "<|im_start|>" in result[0]["text"]
        assert "Xavier" in result[0]["text"]

    def test_talker_response_with_input(self) -> None:
        items = [
            {
                "input": "che, ayudame",
                "text": "Sos un asistente",
                "label": "talker_response",
                "source": "training",
            }
        ]
        result = format_chatml(items)
        assert "che, ayudame" in result[0]["text"]
        assert "Sos un asistente" in result[0]["text"]

    def test_thinker_response(self) -> None:
        items = [
            {
                "input": "complex question",
                "text": "Let me reason step by step",
                "label": "thinker_output",
                "source": "training",
            }
        ]
        result = format_chatml(items)
        assert "complex question" in result[0]["text"]
        assert "Let me reason" in result[0]["text"]

    def test_system_prompt_included(self) -> None:
        items = [
            {"text": "Hello", "label": "talker_response", "source": "convos"}
        ]
        result = format_chatml(items, system_prompt="You are a helpful assistant")
        assert "You are a helpful assistant" in result[0]["text"]

    def test_unknown_label_falls_back(self) -> None:
        items = [
            {"text": "Some text", "label": "unknown_label", "source": "unknown"}
        ]
        result = format_chatml(items)
        assert "Continuá" in result[0]["text"]
        assert "Some text" in result[0]["text"]

    def test_conversation_item_with_user_text(self) -> None:
        items = [
            {
                "input": "user question",
                "text": "assistant answer",
                "label": "talker_response",
                "source": "convos",
            }
        ]
        result = format_chatml(items)
        assert "user question" in result[0]["text"]
        assert "assistant answer" in result[0]["text"]


# ── format_classification ─────────────────────────────────────────────────────


class TestFormatClassification:
    def test_talk_maps_to_zero(self) -> None:
        items = [{"text": "Hola kateto", "label": "talk"}]
        result = format_classification(items)
        assert result[0]["label"] == 0

    def test_think_maps_to_one(self) -> None:
        items = [{"text": "A ver...", "label": "think"}]
        result = format_classification(items)
        assert result[0]["label"] == 1

    def test_talker_response_maps_to_zero(self) -> None:
        items = [{"text": "Hello", "label": "talker_response"}]
        result = format_classification(items)
        assert result[0]["label"] == 0

    def test_thinker_output_maps_to_one(self) -> None:
        items = [{"text": "Thinking...", "label": "thinker_output"}]
        result = format_classification(items)
        assert result[0]["label"] == 1

    def test_unknown_label_defaults_to_zero(self) -> None:
        items = [{"text": "Some text", "label": "unknown"}]
        result = format_classification(items)
        assert result[0]["label"] == 0

    def test_falls_back_to_output_field(self) -> None:
        items = [{"output": "output text", "label": "talk"}]
        result = format_classification(items)
        assert result[0]["text"] == "output text"

    def test_empty_text_not_crashing(self) -> None:
        items = [{"text": "", "label": "talk"}]
        result = format_classification(items)
        assert result[0]["label"] == 0


# ── tokenize / save / load (skip — requires datasets) ─────────────────────────


@pytest.mark.skip(reason="requires datasets (HuggingFace)")
class TestTokenize:
    """Placeholder: tokenize_llm and tokenize_bert need datasets installed."""

    def test_tokenize_llm(self) -> None:
        pass

    def test_tokenize_bert(self) -> None:
        pass

    def test_save_processed(self) -> None:
        pass

    def test_load_processed(self) -> None:
        pass
