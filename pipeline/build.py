"""Run the feasibility spike, then emit the web artifact."""

from __future__ import annotations

import argparse
import json
import traceback

from pipeline.config import DATA_REPORTS, ensure_dirs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build RxGap data")
    parser.add_argument(
        "--skip-cms",
        action="store_true",
        help="Skip the CMS retail-access cross-check",
    )
    args = parser.parse_args()
    ensure_dirs()
    steps = []

    def step(name: str, fn):
        print(f"\n=== {name} ===", flush=True)
        try:
            fn()
            steps.append({"name": name, "ok": True})
        except Exception as exc:
            traceback.print_exc()
            steps.append({"name": name, "ok": False, "error": str(exc)})
            if name in {"overture", "graph"}:
                raise

    if not args.skip_cms:
        from pipeline import cms_check

        step("cms", cms_check.extract_ma)

    from pipeline import extract_overture, pharmacies, graph, demand, access, export

    step("overture", extract_overture.run)
    step("pharmacies", pharmacies.run)
    step("graph", graph.run)
    step("demand", demand.run)
    step("access", access.run)
    step("export", export.run)

    (DATA_REPORTS / "spike.json").write_text(json.dumps({"steps": steps}, indent=2), encoding="utf-8")
    print("\nSpike steps:", json.dumps(steps, indent=2), flush=True)


if __name__ == "__main__":
    main()
