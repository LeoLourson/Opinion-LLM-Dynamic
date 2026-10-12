"""Файлы проекта: конфигурация, профили моделей, каталог runs/v2."""
import copy
import hashlib
import json
import re
from pathlib import Path

# Остальные модули обращаются к store.ROOT, чтобы тесты могли подменить корень.
ROOT = Path(__file__).resolve().parent.parent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    """Запись через временный файл: прерванная запись не портит прежнее содержимое."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def config():
    return read_json(ROOT / "config.json")


def topics():
    return read_json(ROOT / "topics.json")


def profile(name):
    """Профиль модели из config.json с проверкой, что по нему можно запускать опыт."""
    value = copy.deepcopy(config()["profiles"][name])
    if value.get("transport") not in ("api", "subagent"):
        raise ValueError("Неизвестный транспорт профиля")
    if value["transport"] == "subagent" and value.get("engine") not in ("codex", "claude-code"):
        raise ValueError("Неизвестный движок субагента")
    if value["transport"] == "api" and (value.get("engine") != "deepseek" or value.get("settings")):
        raise ValueError("API поддерживает DeepSeek с пустыми settings")
    if not isinstance(value.get("model"), str) or not value["model"].strip():
        raise ValueError(f"Укажите точную модель в profiles.{name}.model")
    if not isinstance(value.get("settings"), dict):
        raise ValueError("settings должны быть объектом")
    return {"id": name, **value}


def protocol_digest():
    """Хеш всего, что определяет ход диалога: темы, тексты участникам, длина диалога.

    Профили моделей сюда не входят: они записаны в самом опыте. Инструкции
    оркестратору и участнику (agents/) тоже не входят.
    """
    cfg = config()
    files = [ROOT / "topics.json", ROOT / "prompts/catalog.json", *sorted((ROOT / "prompts").glob("*.txt"))]
    limits = json.dumps([cfg["rounds"], cfg["message_length"], cfg["api"]["max_tokens"]]).encode()
    return hashlib.sha256(b"".join(p.read_bytes() for p in files) + limits).hexdigest()[:12]


def run_file(kind, ident):
    """Путь runs/v2/<kind>/<ident>.json; kind — state, results, requests, selections, plans."""
    if not re.fullmatch(r"[a-f0-9]{24}", ident):
        raise ValueError("Некорректный ID")
    return ROOT / "runs/v2" / kind / f"{ident}.json"


def relative(path):
    return path.relative_to(ROOT).as_posix()


def check_stop():
    if (ROOT / "STOP").exists():
        raise RuntimeError("Найден файл STOP")
