import argparse
import sys

import uvicorn


def _print_status(args) -> None:
    from .api import db, ingest_once
    from .config import settings
    from .vectors import OllamaClient

    client = OllamaClient()
    up = client.is_up()
    models = client.available_models() if up else []
    print(f"app            : {settings.app_name}")
    print(f"ollama         : {settings.ollama_url} -> {'up' if up else 'DOWN (install from https://ollama.com)'}")
    print(f"models         : {', '.join(models) if models else '(none pulled yet; try: ollama pull llama3.2)'}")
    print(f"embed model    : {settings.embed_model}")
    print(f"chat model     : {settings.chat_model}")
    print(f"base currency  : {settings.base_currency}")
    print(f"fetch source   : {settings.fetch_source}")
    print(f"observations   : {db.count_observations()}")
    print(f"rag documents  : {db.count_documents()}")
    status = db.source_status()
    last = status.get(settings.fetch_source, {}).get("last_success")
    error = status.get(settings.fetch_source, {}).get("last_error")
    print(f"last ingest    : {last or 'never'} {('ERROR: ' + error) if error else ''}")


def cmd_seed(args) -> None:
    from .api import ingest_once

    result = ingest_once()
    if result.ok:
        print(f"OK: fetched {result.fetched} rates, stored {result.stored}, indexed {result.indexed} from {result.source}.")
    else:
        print(f"FAILED: {result.error}")
        sys.exit(1)


def cmd_query(args) -> None:
    from .api import db
    from .rag import answer_question

    answer = answer_question(db, args.question)
    print(f"[engine: {answer.engine}]")
    print(answer.answer)
    if args.verbose:
        print("\nSources used by the RAG retriever:")
        for source in answer.sources:
            print(f"  score={source.score:.4f}  {source.content}")


def cmd_serve(args) -> None:
    uvicorn.run("shinefx.api:app", host=args.host, port=args.port, reload=args.reload)


def cmd_rebuild(args) -> None:
    from .api import db
    from .rag import index_observations

    count = index_observations(db, hours=args.hours)
    print(f"Rebuilt RAG index with {count} documents.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="shinefx", description="ShineFX currency intelligence RAG engine")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show engine status").set_defaults(func=_print_status)

    p_seed = sub.add_parser("seed", help="fetch live rates and index them into the RAG store")
    p_seed.set_defaults(func=cmd_seed)

    p_query = sub.add_parser("query", help="ask the RAG/AI engine a question")
    p_query.add_argument("question")
    p_query.add_argument("-v", "--verbose", action="store_true", help="show retrieved sources")
    p_query.set_defaults(func=cmd_query)

    p_rebuild = sub.add_parser("rebuild", help="rebuild the RAG document index from stored observations")
    p_rebuild.add_argument("--hours", type=int, default=48)
    p_rebuild.set_defaults(func=cmd_rebuild)

    p_serve = sub.add_parser("serve", help="run the API server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
