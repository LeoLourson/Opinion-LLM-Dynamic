"""Тексты, которые видят участники диалога: шаблоны prompts/*.txt и каталог стратегий."""
from . import store


def text(name):
    return (store.ROOT / "prompts" / f"{name}.txt").read_text(encoding="utf-8").strip()


def catalog():
    return store.read_json(store.ROOT / "prompts/catalog.json")


def conditions():
    """Контроль и по одному условию на каждую небазовую стратегию; базовая стоит первой в группе."""
    return ["control"] + [f"{facet}:{level}" for facet, group in catalog()["FACETS"].items()
                          for level in list(group["levels"])[1:]]


def social_conditions():
    return list(catalog()["SOCIAL_CONDITIONS"])


def control_line(mode, round_index, stance):
    """Реплика собеседника в калибровке: возражение без доводов (bare) или просьба рассказать (neutral)."""
    lines = catalog()["BARE_LINES" if mode == "bare" else "NEUTRAL_LINES"]
    if round_index >= len(lines):
        raise ValueError("Недостаточно контрольных реплик для числа раундов")
    return lines[round_index].format(stance=stance)


def attacker_system(topic, condition, social, stance):
    """Инструкция атакующей: роль, стратегия условия, социальные правила, формат."""
    cat = catalog()
    strategy = ""
    if condition != "control":
        facet_name, level_name = condition.split(":")
        facet = cat["FACETS"][facet_name]
        level = facet["levels"][level_name]
        strategy = text("strategy").format(facet=facet["title"].lower(), label=level["label"],
                                           instruction=level["instruction"])
    factors, chosen = cat["SOCIAL_FACTORS"], cat["SOCIAL_CONDITIONS"][social]
    role = factors["role"][chosen["role"]]
    rules = [factors[name][chosen[name]] for name in ("ai_disclosure", "goal_disclosure", "forbidden_list")]
    rules = [rule for rule in rules if rule]
    rules_block = "\n# Правила\n\n" + "\n".join(f"- {rule}" for rule in rules) + "\n" if rules else ""
    return text("attacker_system").format(
        topic=topic, stance=cat["ATTACKER_STANCE_TEXT"][stance], role=f"{role}\n" if role else "",
        strategy=strategy, rules=rules_block, msg_len=store.config()["message_length"])
