from __future__ import annotations

import argparse
import logging

from workbench_runner.config import load_settings
from workbench_runner.worker import run_forever


def main() -> None:
    parser = argparse.ArgumentParser(prog="workbench-runner")
    parser.add_argument(
        "--once",
        action="store_true",
        help="最多处理一个 queued 任务后退出，便于测试或 systemd timer",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_forever(load_settings(), once=args.once)


if __name__ == "__main__":
    main()
