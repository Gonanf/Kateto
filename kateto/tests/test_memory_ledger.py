from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from kateto.voices.base import VoiceAgent
from kateto.voices.ledger import VoiceMemoryLedger
from kateto.voices.tools import BUILTIN_TOOLS, VoiceToolExecutor

from kateto.tests.conversation_support import StreamingFixtureProvider, write_references


def _ledger(tmp_path: Path, dept: str = "fun") -> VoiceMemoryLedger:
    return VoiceMemoryLedger.for_dept(config_dir=tmp_path, dept=dept)


def _read_file(tmp_path: Path, dept: str) -> list[dict[str, object]]:
    path = tmp_path / "memory" / f"{dept}.json"
    content = path.read_text(encoding="utf-8").strip()
    return json.loads(content) if content else []


@pytest.mark.asyncio
async def test_ledger_add_replace_remove_with_unique_substring(tmp_path: Path) -> None:
    # Given: an empty fun-department ledger.
    ledger = _ledger(tmp_path)

    # When: two facts are added.
    assert (await ledger.refine(fact="user prefers async planning", category="facts", evidence="said on monday"))[
        "action"
    ] == "added"
    assert (await ledger.refine(fact="user avoids meetings before 10am", category="facts"))["action"] == "added"

    # Then: both persist with validation.
    assert len(ledger.entries(category="facts")) == 2

    # When: the first fact is replaced via a short unique substring.
    result = await ledger.refine(
        fact="user strongly prefers async planning",
        category="facts",
        evidence="async planning",
    )
    # Then: the entry was replaced, not duplicated.
    assert result["action"] == "replaced"
    facts = ledger.entries(category="facts")
    assert len(facts) == 2
    assert facts[0]["fact"] == "user strongly prefers async planning"

    # When: an entry is removed via a unique substring.
    removed = await ledger.refine(fact="", category="facts", evidence="meetings before 10am")
    # Then: it is gone and the other entry remains.
    assert removed["action"] == "removed"
    facts = ledger.entries(category="facts")
    assert len(facts) == 1
    assert facts[0]["fact"] == "user strongly prefers async planning"


@pytest.mark.asyncio
async def test_ledger_ambiguous_and_missing_substring_fail_safely(tmp_path: Path) -> None:
    # Given: two facts sharing a common prefix.
    ledger = _ledger(tmp_path)
    await ledger.refine(fact="user likes dark mode", category="facts")
    await ledger.refine(fact="user likes dark roast coffee", category="facts")

    # When: a substring matches both entries.
    with pytest.raises(ValueError, match="ambiguous"):
        await ledger.refine(fact="user likes dark chocolate", category="facts", evidence="user likes dark")
    # Then: the ambiguous replace is rejected AND the ledger is unchanged.
    assert len(ledger.entries(category="facts")) == 2

    # When: a substring matches nothing.
    with pytest.raises(ValueError, match="no facts entry contains"):
        await ledger.refine(fact="", category="facts", evidence="nonexistent memory")
    # Then: nothing is removed.
    assert len(ledger.entries(category="facts")) == 2


@pytest.mark.asyncio
async def test_ledger_invalid_entry_rolls_back_snapshot_and_keeps_file(tmp_path: Path) -> None:
    # Given: a ledger with one valid memory.
    ledger = _ledger(tmp_path)
    await ledger.refine(fact="a solid fact", category="facts")

    # When: a mutation fails validation (fact too long).
    with pytest.raises(ValueError, match="too long"):
        await ledger.refine(fact="x" * 500, category="facts")
    # Then: the file still holds the previous valid state, and the failed
    # mutation's snapshot was popped (rollback lands on the pre-fact doc).
    assert [entry["fact"] for entry in _read_file(tmp_path, "fun")] == ["a solid fact"]
    assert await ledger.rollback() == ""
    assert _read_file(tmp_path, "fun") == []

    # When: an unknown category is used.
    await ledger.refine(fact="another fact", category="facts")
    with pytest.raises(ValueError):
        await ledger.refine(fact="whatever", category="bogus")
    # Then: no snapshot was pushed and the document is untouched.
    assert [entry["fact"] for entry in _read_file(tmp_path, "fun")] == ["another fact"]


@pytest.mark.asyncio
async def test_ledger_rollback_restores_previous_document(tmp_path: Path) -> None:
    # Given: two sequential facts in the ledger.
    ledger = _ledger(tmp_path)
    await ledger.refine(fact="memory one", category="facts")
    await ledger.refine(fact="memory two", category="facts")

    # When: the last mutation is rolled back.
    restored = await ledger.rollback()
    # Then: the previous document is back on disk.
    assert json.loads(restored or "[]")[0]["fact"] == "memory one"
    assert [entry["fact"] for entry in ledger.entries(category="facts")] == ["memory one"]


@pytest.mark.asyncio
async def test_ledger_concurrent_refine_does_not_corrupt(tmp_path: Path) -> None:
    # Given: a shared fun-department ledger.
    ledger = _ledger(tmp_path)

    # When: many voices refine the ledger concurrently.
    await asyncio.wait_for(
        asyncio.gather(
            *(
                ledger.refine(fact=f"fact number {index}", category="facts", evidence="")
                for index in range(24)
            )
        ),
        timeout=5,
    )

    # Then: every fact survived, nothing is duplicated, no temp artifacts remain.
    facts = sorted(str(entry["fact"]) for entry in ledger.entries(category="facts"))
    assert facts == sorted(f"fact number {index}" for index in range(24))
    assert not list((tmp_path / "memory").glob(f".{ledger._dept}.json.*.tmp"))


@pytest.mark.asyncio
async def test_ledger_scopes_memory_by_department(tmp_path: Path) -> None:
    # Given: fun and management department ledgers.
    fun = _ledger(tmp_path, dept="fun")
    management = _ledger(tmp_path, dept="management")

    # When: each writes its own fact.
    await fun.refine(fact="stream trivia from yesterday", category="facts")
    await management.refine(fact="sprint review artifacts", category="facts")

    # Then: departments do not mix.
    assert [entry["fact"] for entry in fun.entries(category="facts")] == ["stream trivia from yesterday"]
    assert [entry["fact"] for entry in management.entries(category="facts")] == ["sprint review artifacts"]
    assert (tmp_path / "memory" / "fun.json").is_file()
    assert (tmp_path / "memory" / "management.json").is_file()


@pytest.mark.asyncio
async def test_render_block_is_compact_and_grouped(tmp_path: Path) -> None:
    # Given: a ledger with facts and action patterns but no relationships.
    ledger = _ledger(tmp_path)
    await ledger.refine(fact="user is on vacation next week", category="facts")
    await ledger.refine(fact="daily standup at 9", category="action_patterns")

    # When: the block is rendered.
    block = ledger.render_block()
    # Then: it carries the marker, groups by category, and skips empty ones.
    assert block.startswith("<VOICE_MEMORY>")
    assert block.endswith("</VOICE_MEMORY>")
    assert "facts:" in block
    assert "action_patterns:" in block
    assert "relationships:" not in block
    assert block.count("daily standup at 9") == 1

    # And: an empty ledger renders no block.
    assert _ledger(tmp_path, dept="management").render_block() == ""


@pytest.mark.asyncio
async def test_memory_block_is_frozen_for_session(tmp_path: Path) -> None:
    # Given: a voice whose ledger already holds a memory.
    write_references(tmp_path)
    from kateto.voices.factory import _PROFILES

    ledger = _ledger(tmp_path, dept="fun")
    await ledger.refine(fact="user loves cats", category="facts")
    voice = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=tmp_path,
        provider=StreamingFixtureProvider(),
    )

    # When: the first prompt of the session is built (block frozen here)...
    first_system = (await voice._messages_for("hi", workflow=None, phase_id=None))[0].content
    assert "<VOICE_MEMORY>" in first_system
    # ...and a mid-session write lands in the ledger.
    await ledger.refine(fact="user now owns a dog", category="facts")

    # Then: the second prompt still shows the session-start block, unchanged.
    second_system = (await voice._messages_for("hi again", workflow=None, phase_id=None))[0].content
    assert second_system == first_system
    assert "user now owns a dog" not in second_system


@pytest.mark.asyncio
async def test_refine_memory_tool_roundtrip_and_schema(tmp_path: Path) -> None:
    # Given: an executor for the fun department, plus the advertised tool.
    executor = VoiceToolExecutor(config_dir=tmp_path, dept="fun")
    tool = next(t for t in BUILTIN_TOOLS if t["function"]["name"] == "refine_memory")
    parameters = cast("dict[str, object]", tool["function"].get("parameters") or {})
    required = cast("list[str]", parameters.get("required") or [])
    assert "fact" in required
    assert "category" in required

    # When: the voice refine a memory through the tool.
    added = json.loads(await executor.execute("refine_memory", {"fact": "client budget is 50k", "category": "facts"}))
    assert added["action"] == "added"
    replaced = json.loads(
        await executor.execute(
            "refine_memory",
            {"fact": "client budget is 55k", "category": "facts", "evidence": "budget is 50k"},
        )
    )
    assert replaced["action"] == "replaced"
    removed = json.loads(
        await executor.execute("refine_memory", {"fact": "", "category": "facts", "evidence": "budget is 55k"})
    )
    assert removed["action"] == "removed"
    assert [entry["fact"] for entry in _read_file(tmp_path, "fun")] == []

    # And: a voice without a department cannot write memory.
    solo = VoiceToolExecutor(config_dir=tmp_path)
    denied = json.loads(await solo.execute("refine_memory", {"fact": "x", "category": "facts"}))
    assert "error" in denied