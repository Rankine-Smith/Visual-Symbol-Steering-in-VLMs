"""CLI: python -m vcb {compose,smoke,screen,run,checks,analyse,awareness,reasoning}"""
import argparse
import logging
from pathlib import Path

from .config import load_config, resolve_run_dir


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="vcb")
    ap.add_argument("--config", default=None, help="config file (default: config.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("compose", help="build stimuli/ composites + manifest.csv")
    sub.add_parser("smoke", help="one call per model on q01__none; check logprobs come back")
    sub.add_parser("screen", help="baseline call per candidate statement; writes the screened statement file")
    r = sub.add_parser("run", help="full logprob grid")
    r.add_argument("--dry-run", action="store_true", help="print call count and cost estimate only")
    r.add_argument("--run-id", default=None)
    r.add_argument("--yes", action="store_true", help="allow runs estimated above $3")
    c = sub.add_parser("checks", help="manipulation checks (sees symbol / reads statement)")
    c.add_argument("--run-id", default=None, help="run folder to write into (default: newest)")
    a = sub.add_parser("analyse", help="noise floors, contrasts, verdict -> summary.md")
    a.add_argument("--run-id", default=None)
    for name, hlp in [("awareness", "Method 1: follow-up self-report questions (config `awareness`)"),
                      ("reasoning", "Method 3: reasoning-model samples + summaries (config `reasoning`)")]:
        x = sub.add_parser(name, help=hlp)
        x.add_argument("--dry-run", action="store_true")
        x.add_argument("--run-id", default=None)
        x.add_argument("--yes", action="store_true", help="allow runs estimated above $3")
    args = ap.parse_args()
    cfg = load_config(Path(args.config).resolve()) if args.config else load_config()

    if args.cmd == "compose":
        from .compose import compose_all
        m = compose_all(cfg)
        print(f"Wrote {len(m)} composites; clamped: {int(m.clamped.sum())}")
        print(m.drop_duplicates("condition")[["condition", "symbol_w", "symbol_h", "symbol_area", "target_area", "clamped"]].to_string(index=False))
        print("Font sizes:", m.drop_duplicates("qid").set_index("qid").font_size.to_dict())
    elif args.cmd == "smoke":
        from .run import smoke
        smoke(cfg)
    elif args.cmd == "screen":
        from .run import screen
        screen(cfg)
    elif args.cmd == "run":
        from .run import dry_run, run
        if args.dry_run:
            dry_run(cfg)
        else:
            run(cfg, args.run_id, args.yes)
    elif args.cmd == "checks":
        from .checks import run_checks
        run_checks(cfg, resolve_run_dir(args.run_id))
    elif args.cmd == "analyse":
        from .analysis import analyse
        analyse(resolve_run_dir(args.run_id))
    elif args.cmd in ("awareness", "reasoning"):
        mod = __import__(f"vcb.{args.cmd}", fromlist=["dry_run"])
        if args.dry_run:
            mod.dry_run(cfg)
        else:
            getattr(mod, f"run_{args.cmd}")(cfg, args.run_id, args.yes)


if __name__ == "__main__":
    main()
