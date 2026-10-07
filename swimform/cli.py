"""Command line entry point.

    swimform analyze clip.mp4 --start 10 --end 25
    swimform ask "my legs sink when I breathe"
    swimform serve
    swimform drills --fault low_body_position
    swimform faults
    swimform config --set fps=2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, analyze as analyze_mod, coach, config, report, taxonomy


def _fail(msg: str) -> int:
    print(f"\nerror: {msg}\n", file=sys.stderr)
    return 1


def cmd_analyze(args: argparse.Namespace) -> int:
    print("[swimform] This clip will be sent to Google's Gemini API under your API key. "
          "Adults who have agreed only;\n"
          "           see docs/RESPONSIBLE_USE.md.", file=sys.stderr)
    try:
        result = analyze_mod.analyze(
            args.video, args.start, args.end, args.fps, args.model,
            args.overlays, Path(args.overlay_dir) if args.overlay_dir else None,
            limit=args.drills,
        )
    except (analyze_mod.AnalysisError, config.MissingKey) as e:
        return _fail(str(e))
    except Exception as e:  # noqa: BLE001 — a traceback helps nobody here
        return _fail(f"{type(e).__name__}: {e}")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.markdown:
        print(report.markdown(result))
    else:
        print(report.text(result, verbose=args.verbose))

    if args.out:
        out = Path(args.out).expanduser()
        if out.suffix == ".md":
            out.write_text(report.markdown(result))
        else:
            analyze_mod.save(result, out)
        print(f"saved: {out}", file=sys.stderr)
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    analysis = None
    if args.context:
        try:
            analysis = json.loads(Path(args.context).expanduser().read_text())
        except (OSError, json.JSONDecodeError) as e:
            return _fail(f"could not read --context: {e}")

    question = " ".join(args.question).strip()
    history: list[dict] = []
    interactive = not question

    if interactive:
        print("Ask about your freestyle technique. Blank line or Ctrl-D to quit.\n")

    while True:
        if interactive:
            try:
                question = input("you > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not question:
                return 0

        try:
            res = coach.ask(question, analysis, history, args.model)
        except (coach.CoachError, config.MissingKey) as e:
            return _fail(str(e))
        except Exception as e:  # noqa: BLE001
            return _fail(f"{type(e).__name__}: {e}")

        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print()
            print(res["answer"])
            if res["faults"]:
                print("\nlikely causes:")
                for f in res["faults"]:
                    print(f"  {f['likelihood']:.2f}  {f['faultName']} — {f['why']}")
            if res["drills"]:
                print("\ndrills referenced:")
                for d in res["drills"]:
                    print(f"  {d['title']}")
                    print(f"    {d['summary']}")
            print()

        if not interactive:
            return 0
        history += [{"role": "swimmer", "text": question},
                    {"role": "coach", "text": res["answer"]}]


def cmd_serve(args: argparse.Namespace) -> int:
    from . import server
    return server.serve(args.port, args.host, args.open, tuple(args.allow_host or ()))


def cmd_faults(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(taxonomy.faults(), indent=2, ensure_ascii=False))
        return 0
    for f in taxonomy.faults():
        n = len(taxonomy.drills_for_fault(f["id"]))
        print(f"\n{f['id']}  ({f['name']})")
        print(f"  {f['short']}")
        print(f"  best seen from: {f['plane']}   drills: {n}   status: {f['status']}")
        print(f"  why: {f['why']}")
    print()
    return 0


def cmd_drills(args: argparse.Namespace) -> int:
    if args.fault:
        if args.fault not in taxonomy.fault_ids():
            return _fail(f"unknown fault '{args.fault}'. Try: swimform faults")
        records = taxonomy.drills_for_fault(args.fault)
        print(f"\n{len(records)} drills for {taxonomy.fault_name(args.fault)}\n")
    else:
        records = taxonomy.drills()
        print(f"\n{len(records)} drills\n")

    if args.json:
        print(json.dumps([taxonomy.drill_public(d) for d in records],
                         indent=2, ensure_ascii=False))
        return 0

    for d in records:
        kit = ", ".join(d["equipment"]) or "—"
        print(f"{d['id']:24s} {d['title']}")
        print(f"{'':24s} kit: {kit}   relevance: {d['triathlon_relevance']}")
        if args.verbose:
            print(f"{'':24s} {d['summary']}")
            for l in d["corrects_faults"]:
                print(f"{'':24s} {l['strength']:9s} {taxonomy.fault_name(l['faultId'])}")
            if d.get("caution"):
                print(f"{'':24s} caution: {d['caution']}")
    print()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    if args.set:
        patch = dict(config.load())
        for pair in args.set:
            if "=" not in pair:
                return _fail(f"--set expects key=value, got '{pair}'")
            k, v = pair.split("=", 1)
            if k not in config.DEFAULTS:
                return _fail(f"unknown key '{k}'. Known: {', '.join(config.DEFAULTS)}")
            try:
                patch[k] = json.loads(v)
            except json.JSONDecodeError:
                patch[k] = v
        config.save(patch)
        print(f"saved to {config.CONFIG_PATH}")
    print(json.dumps(config.load(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="swimform",
        description="Freestyle technique analysis from a video of yourself swimming.",
    )
    ap.add_argument("--version", action="version", version=f"swimform {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="analyse a video of yourself swimming")
    a.add_argument("video")
    a.add_argument("--start", type=float, help="seconds into the file to start")
    a.add_argument("--end", type=float, help="seconds into the file to stop")
    a.add_argument("--fps", type=float,
                   help="frames per second the model samples (default 2; a stroke is ~1.2s)")
    a.add_argument("--model", help="pin one model instead of the fallback chain")
    a.add_argument("--overlays", type=int, help="how many annotated frames to render")
    a.add_argument("--overlay-dir", help="where to write the overlay PNGs")
    a.add_argument("--drills", type=int, default=6, help="how many drills to prescribe")
    a.add_argument("--out", help="also write the result here (.json or .md)")
    a.add_argument("--json", action="store_true", help="print raw JSON")
    a.add_argument("--markdown", action="store_true", help="print a markdown report")
    a.add_argument("-v", "--verbose", action="store_true")
    a.set_defaults(func=cmd_analyze)

    q = sub.add_parser("ask", help="ask about technique; no arguments starts a chat")
    q.add_argument("question", nargs="*")
    q.add_argument("--context", help="an analysis .json to answer against")
    q.add_argument("--model")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_ask)

    s = sub.add_parser("serve", help="run the local web app")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 exposes it to your network — see the README first")
    s.add_argument("--open", action="store_true", help="open the app in your browser")
    s.add_argument("--allow-host", action="append", metavar="HOST:PORT",
                   help="with --host, an extra Host header to accept (e.g. a LAN name)")
    s.set_defaults(func=cmd_serve)

    f = sub.add_parser("faults", help="list the technique faults this tool knows")
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_faults)

    d = sub.add_parser("drills", help="browse the drill library")
    d.add_argument("--fault", help="only drills that correct this fault id")
    d.add_argument("--json", action="store_true")
    d.add_argument("-v", "--verbose", action="store_true")
    d.set_defaults(func=cmd_drills)

    c = sub.add_parser("config", help="show or change runtime settings")
    c.add_argument("--set", action="append", metavar="KEY=VALUE")
    c.set_defaults(func=cmd_config)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
