"""Состав порции опытов. План только перечисляет опыты: API и субагенты не вызываются."""
from . import prompts, store, trial

BLOCKS = ("calibration", "pilot", "A", "B", "M")
PILOT_CONDITIONS = ["control", "emotion:anger", "response:active_listening"]
PILOT_REPEAT_OFFSET = 100000  # пробные диалоги не пересекаются с основными повторами 0–4
SAME_TRIAL_KEYS = ("mode", "attacker", "target", "counter", "condition", "social", "repeat", "topic")


def earlier_results():
    """Завершённые опыты по их содержанию, без версии протокола."""
    found = {}
    for path in (store.ROOT / "runs/v2/results").glob("*.json"):
        result = store.read_json(path)
        found.setdefault(store.digest([result[key] for key in SAME_TRIAL_KEYS]), []).append(result["id"])
    return found


def make_plan(block, repeat=0, pairs=None, topic_id=None):
    """Опыты блока для заданных пар.

    calibration — два контрольных диалога на цель; pilot — три условия;
    A — все стратегии; B — все социальные варианты; M — контроль на каждой паре.
    Контрольный диалог входит в A, B и M с одним ID и проводится один раз.
    """
    if block not in BLOCKS or repeat < 0:
        raise ValueError("Неизвестный блок или отрицательный номер повтора")
    cfg = store.config()
    pairs = pairs or (list(cfg["model_pairs"]) if block == "M" else [cfg["main_pair"]])
    conditions = (PILOT_CONDITIONS if block == "pilot" else
                  prompts.conditions() if block == "A" else ["control"])
    socials = prompts.social_conditions() if block == "B" else ["base"]
    modes = ["bare", "neutral"] if block == "calibration" else ["persuade"]
    trial_repeat = repeat + (PILOT_REPEAT_OFFSET if block == "pilot" else 0)

    earlier = earlier_results()
    jobs = {}
    for pair in pairs:
        for mode in modes:
            for condition in conditions:
                for social in socials:
                    item = trial.spec(pair=pair, mode=mode, condition=condition, social=social,
                                      repeat=trial_repeat, topic_id=topic_id)
                    same = earlier.get(store.digest([item[key] for key in SAME_TRIAL_KEYS]), [])
                    jobs[item["id"]] = {
                        "id": item["id"], "pair": pair, "mode": mode, "condition": condition,
                        "social": social, "repeat": trial_repeat,
                        "done": item["id"] in same,
                        # Тот же опыт, проведённый при другой версии протокола.
                        "earlier_results": [ident for ident in same if ident != item["id"]]}
    protocol = store.protocol_digest()
    path = store.run_file("plans", store.digest([block, repeat, pairs, topic_id, protocol]))
    result = {"block": block, "repeat": repeat, "pairs": pairs, "topic_id": topic_id,
              "protocol": protocol, "jobs": list(jobs.values())}
    store.write_json(path, result)
    return {**result, "plan_file": store.relative(path)}
