from __future__ import annotations

import shutil
from pathlib import Path

from build_etf_local_fallback import build_payload, write_payload


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def copy_path(name: str) -> None:
    source = ROOT / name
    target = DIST / name
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def copy_outputs() -> None:
    output_target = DIST / "outputs"
    output_target.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.csv", "*.json", "*.js"):
        for source in sorted((ROOT / "outputs").glob(pattern)):
            shutil.copy2(source, output_target / source.name)
    write_payload(output_target / "etf_local_data.js", build_payload(ROOT / "outputs"))


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    for name in ["index.html", "web"]:
        copy_path(name)
    copy_outputs()
    (DIST / ".nojekyll").touch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
