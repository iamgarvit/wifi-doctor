"""Parsing helpers, and the smart truncation the app relies on."""

from __future__ import annotations

from wifi_doctor.logparse import (
    ctrl_events,
    find,
    min_signal,
    split_lines,
    transitions,
    truncate_for_prompt,
)


def test_split_lines_does_not_invent_a_trailing_blank():
    assert split_lines("a\nb\n") == ["a", "b"]
    assert split_lines("a\nb") == ["a", "b"]


def test_transitions_are_one_based(dev_cases):
    lines = split_lines(dev_cases[0]["log"])
    for t in transitions(lines):
        assert f"{t.frm} -> {t.to}" in lines[t.line_no - 1]


def test_ctrl_events_are_one_based(dev_cases):
    lines = split_lines(dev_cases[0]["log"])
    for line_no, event, _ in ctrl_events(lines):
        assert event in lines[line_no - 1]


def test_find_is_case_insensitive_and_bounded():
    lines = ["Alpha BETA", "gamma", "beta again"]
    assert [n for n, _ in find(lines, "beta")] == [1, 3]
    assert len(find(lines, ".", max_hits=2)) == 2


def test_find_falls_back_to_substring_on_a_bad_regex():
    assert find(["a[b", "c"], "[b") == [(1, "a[b")]


def test_min_signal_picks_the_weakest():
    assert min_signal(["signal=-40", "signal=-83", "signal=-55"]) == -83
    assert min_signal(["nothing here"]) is None


def test_truncate_is_a_noop_below_the_limit():
    lines = [f"line {i}" for i in range(50)]
    nums, kept = truncate_for_prompt(lines, max_lines=2000)
    assert kept == lines and nums == list(range(1, 51))


def test_truncate_preserves_original_line_numbers_and_the_budget():
    noise = ["Sep 25 19:04:12 host CRON: nothing interesting"] * 400
    signal = ["Sep 25 19:04:12 host wpa_supplicant[9]: wlan0: State: ASSOCIATED -> 4WAY_HANDSHAKE"]
    lines = noise + signal + noise
    nums, kept = truncate_for_prompt(lines, max_lines=100)
    assert len(kept) == len(nums) <= 100
    assert all(kept[i] == lines[n - 1] for i, n in enumerate(nums))
    assert nums == sorted(nums)


def test_truncate_keeps_the_state_transition_it_was_given(dev_cases):
    lines = split_lines(dev_cases[0]["log"])
    anchors = {t.line_no for t in transitions(lines)}
    nums, _ = truncate_for_prompt(lines, max_lines=max(40, len(lines) // 2))
    assert anchors & set(nums)
