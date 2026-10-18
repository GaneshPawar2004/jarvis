"""Start JARVIS."""
import argparse
import sys

from interfaces import cli

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. assistant")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--voice", action="store_true", help="start the voice interface")
    mode.add_argument("--hud", action="store_true", help="start the browser dashboard")
    mode.add_argument("--vault", action="store_true", help="manage your saved personal details")
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
    else:
        cli.run()
