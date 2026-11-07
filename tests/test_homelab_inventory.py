from pathlib import Path

import pytest

from ancilla_bot.homelab import inventory as inv

ROOT = Path(__file__).resolve().parents[1]

BASE = """
hosts:
  - {id: a, name: A, os: ubuntu}
services:
  - {id: s1, name: S1, host: a, kind: docker, depends_on: [s2]}
  - {id: s2, name: S2, host: a, kind: systemd, depends_on: [s3]}
  - {id: s3, name: S3, host: a, kind: http}
"""


def test_example_is_valid():
    i = inv.parse_inventory((ROOT / "homelab.yaml.example").read_text(encoding="utf-8"))
    assert len(i.hosts) == 5 and i.service("prometheus")


@pytest.mark.parametrize(
    "old,new,msg",
    [
        ("{id: s3,", "{id: s2,", "重複"),
        ("{id: s3,", "{id: S_3,", "services[2].id"),
        ("host: a, kind: http", "host: zzz, kind: http", "未知の host 'zzz'"),
        ("depends_on: [s3]", "depends_on: [nope]", "未知の service 'nope'"),
        ("kind: http", "kind: bogus", "services[2].kind"),
        ("os: ubuntu", "os: beos", "hosts[0].os"),
    ],
)
def test_validation_errors(old, new, msg):
    with pytest.raises(inv.InventoryError, match=msg.replace("[", r"\[").replace("]", r"\]")):
        inv.parse_inventory(BASE.replace(old, new, 1))


def test_impact_is_transitive_and_cycle_terminates():
    i = inv.parse_inventory(BASE)
    assert i.dependents("s3") == ["s2", "s1"]
    assert i.dependencies("s1") == ["s2", "s3"]
    cyc = inv.parse_inventory(BASE.replace("kind: http", "kind: http, depends_on: [s1]"))
    assert set(cyc.dependents("s1")) == {"s2", "s3"}
    assert "s1" not in cyc.dependencies("s1")


def test_reload_and_tool_errors(tmp_path, monkeypatch):
    p = tmp_path / "h.yaml"
    p.write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("ANCILLA_HOMELAB_PATH", str(p))
    monkeypatch.setattr(inv, "_cache", None)
    assert "s3" in inv.homelab_list_services(host="a")
    assert "s1" in inv.homelab_inspect(id="s3")
    p.write_text("hosts: [", encoding="utf-8")  # 壊れた YAML: 例外でなくエラー文字列
    assert inv.homelab_list_hosts().startswith("Error:")
    p.write_text(BASE + "  - {id: s4, name: S4, host: a, kind: http}\n", encoding="utf-8")
    assert "s4" in inv.homelab_list_services()
