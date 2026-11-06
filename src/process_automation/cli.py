import argparse
import json
from datetime import datetime
from pathlib import Path
from zipfile import BadZipFile

import uvicorn
from sqlalchemy.exc import SQLAlchemyError

from .app import configured_dispatcher
from .database import configured_store
from .domain import configured_clock
from .excel import import_requests, write_report
from .service import Service


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic request process tools")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--service", choices=["app", "mock-graph", "mock-teams"], default="app")
    serve.add_argument("--port", type=int, default=8000)
    report = commands.add_parser("report")
    report.add_argument("--out", type=Path, required=True)
    report.add_argument("--as-of")
    load = commands.add_parser("import-excel")
    load.add_argument("file", type=Path)
    load.add_argument("--actor", default="mira")
    load.add_argument("--out", type=Path, required=True)
    reminder = commands.add_parser("remind")
    reminder.add_argument("--as-of")
    commands.add_parser("deliver")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            module = {"app": "app", "mock-graph": "mock_graph", "mock-teams": "mock_teams"}[args.service]
            uvicorn.run(f"process_automation.{module}:create_app", factory=True, host="127.0.0.1", port=args.port)
            return 0
        store = configured_store()
        clock = configured_clock()
        service, dispatcher = Service(store, clock), configured_dispatcher(store)
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if getattr(args, "as_of", None) else clock()
        if args.command == "report":
            with store.sessions() as session:
                metrics = write_report(session, args.out, as_of)
            print(json.dumps({"file": str(args.out), "open": len(metrics["open"]), "overdue": len(metrics["overdue"]), "average_processing_hours": metrics["average_processing_hours"]}))
        elif args.command == "import-excel":
            rows = import_requests(args.file, service, dispatcher, args.actor)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(rows))
            return 1 if any(row["status"] == "error" for row in rows) else 0
        elif args.command == "remind":
            with store.sessions() as session:
                queued = service.reminders(session, "nolan", as_of)
            print(json.dumps({"queued": queued, **dispatcher.deliver()}))
        else:
            print(json.dumps(dispatcher.deliver()))
    except (ValueError, OSError, BadZipFile, SQLAlchemyError) as error:
        print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
