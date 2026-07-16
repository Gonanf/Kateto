from __future__ import annotations

from scripts.qa.acceptance import _owned_processes, _owned_listeners, _parse_process_snapshot


def test_cleanup_attribution_ignores_preexisting_processes_and_listeners() -> None:
    # Given: the baseline contains unrelated tracker/pytest processes and a listener.
    baseline = _parse_process_snapshot(
        "101 101 /usr/bin/python -c resource_tracker\n"
        "102 102 /usr/bin/pytest -q\n"
        "103 103 /usr/bin/python -m kateto old-run\n"
    )
    current = _parse_process_snapshot(
        "101 101 /usr/bin/python -c resource_tracker\n"
        "102 102 /usr/bin/pytest -q\n"
        "103 103 /usr/bin/python -m kateto old-run\n"
    )

    # When: cleanup attributes current state to this invocation's process groups.
    owned = _owned_processes(current, baseline, {201})
    listeners = _owned_listeners(
        {"LISTEN 0 128 127.0.0.1:9000 users:(\"python\",pid=103,fd=3)"},
        {"LISTEN 0 128 127.0.0.1:9000 users:(\"python\",pid=103,fd=3)"},
        current,
        {201},
    )

    # Then: unrelated pre-existing resources are not reported as owned leaks.
    assert owned == []
    assert listeners == []


def test_cleanup_attribution_ignores_new_listener_outside_owned_process_group() -> None:
    # Given: an unrelated listener appears after the smoke baseline.
    current = _parse_process_snapshot(
        "103 103 /usr/bin/python -m unrelated-service\n"
        "201 201 /usr/bin/python -m kateto\n"
    )

    # When: cleanup attributes the listener using its owning PID and process group.
    listeners = _owned_listeners(
        {"LISTEN 0 128 127.0.0.1:9000 users:(\"python\",pid=103,fd=3)"},
        set(),
        current,
        {201},
    )

    # Then: the unrelated listener is not reported as a run-owned leak.
    assert listeners == []


def test_cleanup_attribution_reports_new_owned_processes_and_listeners() -> None:
    # Given: a new tracker and pytest process remain in an invocation-owned group.
    baseline = _parse_process_snapshot("101 101 /usr/bin/python -c resource_tracker\n")
    current = _parse_process_snapshot(
        "101 101 /usr/bin/python -c resource_tracker\n"
        "201 201 /usr/bin/python -c resource_tracker\n"
        "202 201 /usr/bin/pytest -q\n"
    )

    # When: cleanup attributes the post-run snapshot.
    owned = _owned_processes(current, baseline, {201})
    listeners = _owned_listeners(
        {
            'LISTEN 0 128 127.0.0.1:9000 users:("python",pid=201,fd=3)',
            'LISTEN 0 128 127.0.0.1:9001 users:("pytest",pid=202,fd=4)',
        },
        set(),
        current,
        {201},
    )

    # Then: actual invocation-owned leaks remain visible to the cleanup verdict.
    assert owned == [
        "201 201 /usr/bin/python -c resource_tracker",
        "202 201 /usr/bin/pytest -q",
    ]
    assert len(listeners) == 2
