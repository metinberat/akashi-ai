import argparse
import asyncio
import json

from akashi_agent.config import AgentSettings
from akashi_agent.relay import DeviceRelay


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AKASHI secure Windows agent relay")
    subparsers = parser.add_subparsers(dest="command", required=True)
    pair = subparsers.add_parser("pair", help="Pair this desktop with AKASHI Core")
    pair.add_argument("--core-url", required=True)
    pair.add_argument("--code", required=True)
    pair.add_argument("--name", default="AKASHI Desktop")
    run = subparsers.add_parser("run", help="Poll AKASHI Core for approved actions")
    run.add_argument("--once", action="store_true")
    run.add_argument("--interval", type=float, default=3.0)
    subparsers.add_parser("unpair", help="Remove this desktop's local credential")
    serve = subparsers.add_parser("serve", help="Run the authenticated loopback API")
    serve.add_argument("--port", type=int, default=8765)
    return parser


async def _main() -> None:
    args = build_parser().parse_args()
    relay = DeviceRelay(AgentSettings.from_env())
    if args.command == "pair":
        device = await relay.pair(args.core_url, args.code, args.name)
        print(json.dumps(device, ensure_ascii=False, indent=2))
    elif args.command == "run":
        if args.once:
            print(f"Processed {await relay.run_once()} action(s).")
        else:
            await relay.run_forever(args.interval)
    elif args.command == "unpair":
        relay.credentials.remove()
        print("Local device credential removed. Revoke the device in AKASHI as well.")
    elif args.command == "serve":
        import uvicorn

        config = uvicorn.Config(
            "akashi_agent.main:app",
            host="127.0.0.1",
            port=max(1024, min(args.port, 65535)),
            log_level="info",
        )
        await uvicorn.Server(config).serve()


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        # Ctrl+C is a normal operator shutdown, not an agent failure.
        pass
