"""The briefing scheduler: exact-minute entries, and entries that wait for a HUD."""


def schedule():
    return [
        {"at": "07:30", "until": "12:00", "prompt": "Morgen-Briefing"},
        {"at": "21:00", "prompt": "Abend"},
    ]


def keys(due):
    return [key for key, _ in due]


def test_a_waiting_entry_fires_on_the_first_tick_with_a_hud(server_mod):
    """The HUD opened at 07:42: the morning briefing still comes, then."""
    assert server_mod._due_entries(schedule(), "07:30", set(), has_clients=False) == []
    assert keys(server_mod._due_entries(schedule(), "07:42", set(), has_clients=True)) == ["0|07:30"]


def test_a_waiting_entry_fires_only_once_a_day(server_mod):
    assert server_mod._due_entries(schedule(), "08:00", {"0|07:30"}, has_clients=True) == []


def test_a_waiting_entry_neither_starts_early_nor_outlives_its_window(server_mod):
    assert server_mod._due_entries(schedule(), "07:29", set(), has_clients=True) == []
    assert server_mod._due_entries(schedule(), "12:00", set(), has_clients=True) == []


def test_an_entry_without_until_keeps_the_exact_minute_rule(server_mod):
    assert keys(server_mod._due_entries(schedule(), "21:00", set(), has_clients=False)) == ["1|21:00"]
    assert server_mod._due_entries(schedule(), "21:01", set(), has_clients=True) == []
