import argparse
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def test_process_due_timers_fires_once_and_notifies(monkeypatch):
    t0 = datetime(2026, 11, 24, 14, 0, 0, tzinfo=JST)
    now = [t0]
    monkeypatch.setattr(timers, "_now", lambda: now[0])

    seen = []
    timers.subscribe_changes(lambda ev, item: seen.append((ev, item["id"], item["status"])))

    t = timers.create_timer(30, label="お茶")
    assert timers.process_due_timers(now=t0 + timedelta(seconds=29)) == []

    fired = timers.process_due_timers(now=t0 + timedelta(seconds=30))
    assert len(fired) == 1
    assert fired[0]["id"] == t["id"]
    assert fired[0]["status"] == "firing"
    assert fired[0]["fired_at"] == "2026-11-24T14:00:30+09:00"
    assert ("fired", t["id"], "firing") in seen

    # 二重発火しない
    assert timers.process_due_timers(now=t0 + timedelta(seconds=31)) == []

    # 通知キューへ書かれている
    pending = Path(os.environ["ANCILLA_NOTIFICATIONS_DIR"]) / "pending.jsonl"
    records = [json.loads(line) for line in pending.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["title"] == t["id"]
    assert "お茶" in records[0]["message"]

    # 通知が例外を出しても発火自体は壊れない
    monkeypatch.setattr(timers, "append_notification", lambda **kw: (_ for _ in ()).throw(RuntimeError("notify fail")))
    t2 = timers.create_timer(10)
    fired2 = timers.process_due_timers(now=t0 + timedelta(seconds=100))
    assert [x["id"] for x in fired2] == [t2["id"]]


def test_next_due_delay_sec(monkeypatch):
    t0 = datetime(2026, 11, 24, 14, 0, 0, tzinfo=JST)
    monkeypatch.setattr(timers, "_now", lambda: t0)
    assert timers.next_due_delay_sec(now=t0) is None

    timers.create_timer(50)
    timers.create_timer(20)
    assert timers.next_due_delay_sec(now=t0 + timedelta(seconds=5)) == pytest.approx(15.0)
    assert timers.next_due_delay_sec(now=t0 + timedelta(seconds=25)) == 0.0


def test_watcher_loop_wakes_and_fires():
    fired_event = threading.Event()
    fired_ids = []

    def on_ev(ev, item):
        if ev == "fired":
            fired_ids.append(item["id"])
            fired_event.set()

    timers.subscribe_changes(on_ev)
    stop = timers.start_timer_watcher(poll_cap_sec=5.0)
    try:
        time.sleep(0.05)
        t = timers.create_timer(1, label="即時起床")
        assert fired_event.wait(timeout=3.0), "タイマー監視ループが 3 秒以内に発火しませんでした"
        assert t["id"] in fired_ids
        assert timers.get_timer(t["id"])["status"] == "firing"
    finally:
        timers.stop_timer_watcher(stop)


def test_timer_tools_and_skill(monkeypatch, tmp_path):
    from ancilla_bot.runtime.capability import get_capability
    from ancilla_bot.skills.loader import read_skill
    from ancilla_bot.tools.schemas import get_native_parameters

    for name in ("timer_set", "timer_list", "timer_update", "timer_stop", "timer_cancel"):
        assert get_capability(name) is not None
        assert get_native_parameters(name)["type"] == "object"

    assert timers.tool_timer_set(0).startswith("Error:")
    created = json.loads(timers.tool_timer_set(180, label="麺"))
    tid = created["id"]

    listed = json.loads(timers.tool_timer_list())
    assert len(listed["timers"]) == 1 and listed["timers"][0]["id"] == tid

    updated = json.loads(timers.tool_timer_update(tid, add_sec=60, label="うどん"))
    assert updated["label"] == "うどん" and updated["duration_sec"] == 240
    assert timers.tool_timer_update("TMR-9999", label="x").startswith("Error:")

    assert timers.tool_timer_stop(tid).startswith("Error:")
    with timers._conn() as c:
        c.execute("UPDATE timers SET status='firing', fired_at=created_at WHERE id=1")
    stopped = json.loads(timers.tool_timer_stop())
    assert len(stopped["stopped"]) == 1 and stopped["stopped"][0]["status"] == "stopped"

    t2 = json.loads(timers.tool_timer_set(60))
    cancelled = json.loads(timers.tool_timer_cancel(t2["id"]))
    assert cancelled["status"] == "cancelled"
    assert json.loads(timers.tool_timer_list(include_finished="true"))["timers"].__len__() == 2

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(root / "skills"))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path))
    body = read_skill("timers")
    assert not body.startswith("Error:") and "timer_set" in body


def test_timer_cli(capsys):
    from ancilla_bot.cli.commands.timer import cmd_timer

    ns = lambda **k: argparse.Namespace(**k)  # noqa: E731

    assert cmd_timer(ns(timer_command="list", all=False)) == 0
    assert "(タイマーなし)" in capsys.readouterr().out

    assert cmd_timer(ns(timer_command="set", duration_sec=0, label="")) == 1
    assert "Error:" in capsys.readouterr().out

    assert cmd_timer(ns(timer_command="set", duration_sec=90, label="紅茶")) == 0
    assert "TMR-0001" in capsys.readouterr().out

    assert cmd_timer(ns(timer_command="list", all=False)) == 0
    out = capsys.readouterr().out
    assert "TMR-0001" in out and "紅茶" in out

    assert cmd_timer(ns(timer_command="stop", id="")) == 0
    assert "鳴動中のタイマーはありません" in capsys.readouterr().out

    with timers._conn() as c:
        c.execute("UPDATE timers SET status='firing', fired_at=created_at WHERE id=1")
    assert cmd_timer(ns(timer_command="stop", id="TMR-0001")) == 0
    assert "停止しました" in capsys.readouterr().out

    assert cmd_timer(ns(timer_command="set", duration_sec=45, label="")) == 0
    capsys.readouterr()
    assert cmd_timer(ns(timer_command="cancel", id="TMR-0002")) == 0
    assert "取り消しました" in capsys.readouterr().out
    assert cmd_timer(ns(timer_command="cancel", id="TMR-9999")) == 1
    capsys.readouterr()


