"""runner 配置：全部走环境变量，容器与本地一个样。"""

import os
import socket


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


class Config:
    def __init__(self):
        self.platform_url = os.environ.get("PLATFORM_URL", "http://127.0.0.1:8501").rstrip("/")
        self.api_token = os.environ.get("API_TOKEN", "").strip()
        self.poll_seconds = _f("POLL_SECONDS", 5)
        # 单次执行完就退出（调试 / 计划任务用），默认常驻轮询
        self.run_once = os.environ.get("RUN_ONCE", "").strip().lower() in ("1", "true", "yes")
        # 单个 HTTP 请求超时
        self.request_timeout = _f("REQUEST_TIMEOUT", 30)
        # 只处理指定项目的 run（空=全部）
        self.project_id = os.environ.get("PROJECT_ID", "").strip()
        # 内网测试环境常用自签证书：VERIFY_SSL=0 关掉校验（默认开着）
        self.verify_ssl = os.environ.get("VERIFY_SSL", "1").strip().lower() not in (
            "0", "false", "no", "off")
        # ---- UI 用例（P2）----
        # 无头默认开；排查选择器问题时设 HEADLESS=0 能看着浏览器跑
        self.headless = os.environ.get("HEADLESS", "1").strip().lower() not in (
            "0", "false", "no", "off")
        # UI 步骤单步超时（毫秒）：SPA 首屏 + 接口往返，比 API 的 30s 要短才不卡轮次
        self.ui_timeout_ms = int(_f("UI_TIMEOUT_MS", 15000))
        # 失败截图落盘目录（相对项目根）
        self.shot_dir = os.environ.get("UI_SHOT_DIR", "data/uploads/ui").strip()

    def problems(self):
        if not self.api_token:
            return "缺少 API_TOKEN（在平台设置页给 runner 单独建一个）"
        if not self.platform_url.startswith("http"):
            return f"PLATFORM_URL 不合法: {self.platform_url}"
        return ""

    @property
    def runner_id(self):
        """认领时上报的身份：答"这一轮在哪台机器、哪个进程上跑"。"""
        return (os.environ.get("RUNNER_ID", "").strip()
                or f"{socket.gethostname()}:{os.getpid()}")
