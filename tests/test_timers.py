from datetime import datetime, timedelta, timezone

import pytest

from ancilla_bot.assistant import timers


JST = timezone(timedelta(hours=9))


@pytest.fixture(autouse=True)
def _clean_hooks():
    timers.clear_hooks()
    yield
    timers.clear_hooks()


def test_parse_and_format_id():
    assert timers.fmt_id(1) == "TMR-0001"
    assert timers.fmt_id(42) == "TMR-0042"
    assert timers.parse_id("TMR-0001") == 1
    assert timers.parse_id("tmr-12") == 12
    assert timers.parse_id("7") == 7
    assert timers.parse_id(9) == 9
    assert timers.parse_id("0") is None
    assert timers.parse_id(0) is None
    assert timers.parse_id(True) is None
    assert timers.parse_id("nope") is None


def test_create_get_and_list_timers(monkeypatch):
    t0 = datetime(2026, 11, 24, 14, 0, 0, 500000, tzinfo=JST)
    now = [t0]
    monkeypatch.setattr(timers, "_now", lambda: now[0])

    with pytest.raises(ValueError):
        timers.create_timer(0)
    with pytest.raises(ValueError):
        timers.create_timer(-5)
    with pytest.raises(ValueError):
        timers.create_timer(86400 * 7 + 1)
    with pytest.raises(ValueError):
        timers.create_timer(True)

    b = timers.create_timer(300, label=" 紅茶 ", source="companion")
    a = timers.create_timer(60, label="カップ麺")
    assert a["id"] == "TMR-0002"
    assert b["id"] == "TMR-0001"
    assert b["label"] == "紅茶"
    assert b["source"] == "companion"
    assert b["remaining_sec"] == 300
    assert a["remaining_sec"] == 60
    assert timers.get_timer("tmr-2")["label"] == "カップ麺"
    assert timers.get_timer("TMR-9999") is None

    # 20秒後の残り時間と ends_at 昇順
    now[0] = t0 + timedelta(seconds=20)
    payload = timers.list_timers_payload()
    assert payload["server_now"] == "2026-11-24T14:00:20+09:00"
    assert [x["id"] for x in payload["timers"]] == ["TMR-0002", "TMR-0001"]
    assert payload["timers"][0]["remaining_sec"] == 40
    assert payload["timers"][1]["remaining_sec"] == 280


def test_update_timer(monkeypatch):
    t0 = datetime(2026, 11, 24, 14, 0, 0, tzinfo=JST)
    now = [t0]
    monkeypatch.setattr(timers, "_now", lambda: now[0])

    t = timers.create_timer(180, label="パスタ")
    now[0] = t0 + timedelta(seconds=30)

    # duration_sec で残り時間を変更
    u1 = timers.update_timer(t["id"], duration_sec=300)
    assert u1["duration_sec"] == 300
    assert u1["remaining_sec"] == 300
    assert u1["ends_at"] == "2026-11-24T14:05:30+09:00"

    # add_sec で延長・短縮、label のみ更新
    u2 = timers.update_timer(t["id"], add_sec=-60, label="ゆで卵")
    assert u2["remaining_sec"] == 240
    assert u2["label"] == "ゆで卵"

    u3 = timers.update_timer(t["id"], label="完了確認")
    assert u3["label"] == "完了確認"
    assert u3["remaining_sec"] == 240

    with pytest.raises(ValueError):
        timers.update_timer(t["id"], duration_sec=60, add_sec=10)
    with pytest.raises(ValueError):
        timers.update_timer(t["id"], add_sec=-300)
    with pytest.raises(LookupError):
        timers.update_timer("TMR-9999", label="x")


def test_stop_and_cancel_timer():
    t1 = timers.create_timer(60, label="a")
    t2 = timers.create_timer(120, label="b")
    t3 = timers.create_timer(180, label="c")

    # running は stop_timer できない
    with pytest.raises(ValueError):
        timers.stop_timer(t1["id"])
    with pytest.raises(LookupError):
        timers.stop_timer("TMR-9999")

    # t1, t2 を firing にする
    with timers._conn() as c:
        c.execute("UPDATE timers SET status='firing', fired_at=created_at WHERE id IN (1, 2)")

    # 非 running は時間変更できない
    with pytest.raises(ValueError):
        timers.update_timer(t1["id"], duration_sec=60)

    # t1 を単体 stop → 再度呼んでも冪等
    stopped_one = timers.stop_timer(t1["id"])
    assert len(stopped_one) == 1 and stopped_one[0]["status"] == "stopped"
    assert timers.stop_timer(t1["id"])[0]["status"] == "stopped"

    # 省略時は残っている firing（t2 のみ）を停止
    stopped_all = timers.stop_timer()
    assert [x["id"] for x in stopped_all] == [t2["id"]]
    assert timers.stop_timer() == []

    # t3 を cancel → 冪等、その後の stop は不可
    cancelled = timers.cancel_timer(t3["id"])
    assert cancelled["status"] == "cancelled"
    assert timers.cancel_timer(t3["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        timers.stop_timer(t3["id"])
    with pytest.raises(LookupError):
        timers.cancel_timer("TMR-9999")

    assert [x["id"] for x in timers.list_timers()] == []
    assert len(timers.list_timers(include_finished=True)) == 3


def test_signature_and_change_hooks():
    seen = []

    def cb(ev, item):
        seen.append((ev, item["id"], item["status"]))

    def broken(_ev, _item):
        raise RuntimeError("boom")

    timers.subscribe_changes(broken)
    timers.subscribe_changes(cb)
    timers.subscribe_changes(cb)  # 重複登録されない

    s0 = timers.signature()
    t = timers.create_timer(90)
    s1 = timers.signature()
    assert s1 != s0

    timers.update_timer(t["id"], label="renamed")
    s2 = timers.signature()
    assert s2 != s1

    timers.cancel_timer(t["id"])
    s3 = timers.signature()
    assert s3 != s2

    assert seen == [
        ("changed", t["id"], "running"),
        ("changed", t["id"], "running"),
        ("changed", t["id"], "cancelled"),
    ]
