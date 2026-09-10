"""Start a fresh Streamlit demo without changing the repository's runtime data."""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="banking-demo-") as directory:
        data = Path(directory)
        for filename in ("clientes.csv", "score_limite.csv"):
            copyfile(ROOT / "demo/fixtures" / filename, data / filename)
        environment = {**os.environ, "BANKING_DATA_DIR": str(data)}
        try:
            return subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "streamlit_app.py",
                    "--server.port",
                    str(args.port),
                    "--server.headless",
                    "true",
                ],
                cwd=ROOT,
                env=environment,
            )
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
