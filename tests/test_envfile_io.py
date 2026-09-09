from pathlib import Path

from ancilla_bot.cli.envfile import read_env_map, set_values


def test_read_env_map_strips_quotes_skips_comments(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text(
        "# comment\nFOO='bar'\nBAZ=\"qux\"\nPLAIN=ok\n",
        encoding="utf-8",
    )
    assert read_env_map(p) == {"FOO": "bar", "BAZ": "qux", "PLAIN": "ok"}


def test_set_values_preserves_comment_lines(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("# keep\nFOO=old\n", encoding="utf-8")
    changed = set_values({"FOO": "new", "BAR": "added"}, path=p)
    text = p.read_text(encoding="utf-8")
    assert changed == ["FOO", "BAR"]
    assert text.splitlines() == ["# keep", "FOO=new", "BAR=added"]
