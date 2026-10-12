"""Командная строка эксперимента. Команды и порядок работы описаны в README.md.

  poll    --target PROFILE                 начать опрос тем для профиля цели
  plan    --block BLOCK [--pairs ...]      перечислить опыты порции
  start   --pair PAIR [--mode ...] ...     создать опыт
  advance --id ID                          исполнять опыт до запроса субагенту или до конца
  submit  --id ID --file FILE              передать ответ субагента
  status  --id ID                          стадия опыта
"""
import argparse
import json
import sys
from pathlib import Path

from persuasion import plan, store, trial


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("poll")
    p.add_argument("--target", help="Профиль цели; по умолчанию цель основной пары")

    p = commands.add_parser("plan")
    p.add_argument("--block", choices=plan.BLOCKS, required=True)
    p.add_argument("--repeat", type=int, default=0)
    p.add_argument("--pairs", nargs="+", help="Имена пар из config.json")
    p.add_argument("--topic-id", help="Тема вручную вместо выбранной опросом")

    p = commands.add_parser("start")
    p.add_argument("--pair")
    p.add_argument("--mode", choices=["persuade", "bare", "neutral"], default="persuade")
    p.add_argument("--condition", default="control")
    p.add_argument("--social", default="base")
    p.add_argument("--repeat", type=int, default=0)
    p.add_argument("--topic-id", help="Тема вручную вместо выбранной опросом")

    for name in ("advance", "status", "submit"):
        p = commands.add_parser(name)
        p.add_argument("--id", required=True)
        if name == "submit":
            p.add_argument("--file", required=True, help="JSON-конверт с ответом субагента")

    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "poll":
        result = trial.start(mode="poll", target=args["target"])
    elif command == "plan":
        result = plan.make_plan(args["block"], args["repeat"], args["pairs"], args["topic_id"])
    elif command == "start":
        result = trial.start(**args)
    elif command == "submit":
        result = trial.submit(args["id"], store.read_json(Path(args["file"])))
    else:
        result = {"advance": trial.advance, "status": trial.status}[command](args["id"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
