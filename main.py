"""Start JARVIS."""
import argparse
import sys

from interfaces import cli

if __name__ == "__main__":
    if sys.stdout:  # None under pythonw (the background agent)
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. assistant")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--voice", action="store_true", help="start the voice interface")
    mode.add_argument("--hud", action="store_true", help="start the browser dashboard")
    mode.add_argument("--vault", action="store_true", help="manage your saved personal details")
    mode.add_argument("--pair", action="store_true", help="connect this laptop to cloud JARVIS (once)")
    mode.add_argument("--agent", action="store_true", help="run the laptop agent for cloud JARVIS")
    mode.add_argument("--agent-install", action="store_true", help="start the laptop agent at every login")
    mode.add_argument("--agent-uninstall", action="store_true", help="stop starting the agent at login")
    mode.add_argument("--migrate-memory", action="store_true", help="copy local memory to the shared Neon memory")
    parser.add_argument("--lan", action="store_true", help="with --hud: also allow phones on the same Wi-Fi")
    args = parser.parse_args()
    if args.voice:
        from interfaces import voice

        voice.run()
    elif args.vault:
        from interfaces import vault_cli

        vault_cli.run()
    elif args.hud:
        from interfaces.hud import server

        server.run(lan=args.lan)
    elif args.pair or args.agent or args.agent_install or args.agent_uninstall:
        from interfaces import agent

        if args.pair:
            agent.pair()
        elif args.agent:
            agent.run()
        elif args.agent_install:
            agent.install()
        else:
            agent.uninstall()
    elif args.migrate_memory:
        from core import migrate

        migrate.run()
    else:
        cli.run()
