def is_auto(model: str) -> bool:
    return model.strip().lower() == "auto"


def pick_auto(names: list[str], *, setting: str) -> str:
    found = [name for name in names if name]
    if len(found) != 1:
        raise ValueError(f"{setting}=auto はモデルが1件のときだけ使えます（現在 {len(found)} 件）")
    return found[0]
