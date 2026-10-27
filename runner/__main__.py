"""python -m runner：常驻轮询 queued 的 run，认领后串行执行、回填、收尾。

本地跑：
    PLATFORM_URL=http://127.0.0.1:8501 API_TOKEN=atk_xxx python -m runner

只跑一轮就退出（调试/计划任务）：
    RUN_ONCE=1 PLATFORM_URL=... API_TOKEN=... python -m runner
"""

import os
import sys
import time
import traceback

from .auth import build_headers

from . import browser as browser_mod

from .client import ApiError, Platform

from .config import Config

from .executor import execute_case


def _needs_ui(cases):
    """这一轮里有没有页面操作步骤。没有就不起浏览器（省 2 秒启动 + 几百兆内存）。"""
    for c in cases:
        struct = c.get("steps_json") or {}
        if not isinstance(struct, dict):
            continue
        for s in struct.get("steps") or []:
            if isinstance(s, dict) and s.get("ui"):
                return True
    return False


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# Windows 控制台事件类型（SetConsoleCtrlHandler 用）
_CTRL_BREAK_EVENT = 1
_CTRL_CLOSE_EVENT = 2
_CTRL_SHUTDOWN_EVENT = 6
_CTRL_LOGOFF_EVENT = 7


def _install_console_close_guard():
    """让"点 X 关窗口"也走收尾路径（2026-10-26 评审修复）。

    背景：Windows 控制台"点 X"发的是 CTRL_CLOSE_EVENT，CPython 默认处理是
    **直接终止进程**——finally 不执行，已经认领的 run 永远停在 running。
    之前只有 Ctrl+C（KeyboardInterrupt）有兜底，"关窗口不留僵尸"名不副实。

    做法：注册一个控制台处理函数，收到关闭/关机/注销时给自己发一个
    CTRL_BREAK_EVENT——Python 默认处理器会把它转成主线程的 KeyboardInterrupt，
    于是 process() 里既有的"中断 → finish(failed)"逻辑原样生效，不新写收尾代码。
    对本函数自己触发的 BREAK 返回 False 放行，交给 Python 默认处理。
    非 Windows 或注册失败：静默跳过，其他平台行为不变。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        def handler(dwCtrlType):
            if dwCtrlType in (_CTRL_CLOSE_EVENT, _CTRL_SHUTDOWN_EVENT, _CTRL_LOGOFF_EVENT):
                kernel32 = ctypes.windll.kernel32
                # 优先只发给本进程组；失败（本进程不是组组长）再发给同控制台全部
                if not kernel32.GenerateConsoleCtrlEvent(
                        _CTRL_BREAK_EVENT, kernel32.GetCurrentProcessId()):
                    kernel32.GenerateConsoleCtrlEvent(_CTRL_BREAK_EVENT, 0)
                return True      # 事件已处理：别让系统立刻杀进程
            return False         # 其余（含自发送的 BREAK）走默认处理

        _install_console_close_guard._cb = handler   # 持有引用，防被 GC
        ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
    except Exception:                               # noqa: BLE001 注册失败不影响主流程
        pass


def _finish(platform, rid, status, note=""):
    """收尾；已经收过（409）就忽略——兜底路径不能把自己再弄崩。"""
    try:
        return platform.finish(rid, status, note)
    except ApiError as exc:
        log(f"  ! run {rid} 收尾失败（可能已收尾）：{exc}")
        return None


def process(platform, run_row, cfg):
    """认领一轮并跑完。

    外层兜底：runner 被 Ctrl+C / 窗口关掉 / 未预期异常时，把这一轮标 failed
    并写清原因——否则 run 永远停在 running，平台侧只能看到一个僵尸。
    """
    rid = run_row["id"]
    try:
        claim = platform.claim(rid, cfg.runner_id)
    except ApiError as exc:
        log(f"run {rid} 认领失败：{exc}")
        return

    try:
        _run_claimed(platform, rid, claim, cfg)
    except KeyboardInterrupt:
        _finish(platform, rid, "failed", "runner 被中断（Ctrl+C / 窗口关闭）")
        raise
    except Exception as exc:                      # noqa: BLE001 未预期异常也要收尾
        traceback.print_exc()
        _finish(platform, rid, "failed", f"runner 异常退出：{exc}"[:300])


def _run_claimed(platform, rid, claim, cfg):
    run = claim["run"]
    cases = claim.get("cases") or []
    skipped = claim.get("skipped") or []
    env = claim.get("environment") or {}
    variables = claim.get("vars") or {}
    # vars.baseUrl 优先于环境里的 base_url：换内网 IP / 临时切换不用改表
    base_url = (variables.get("baseUrl") or env.get("base_url") or "").strip()
    log(f"认领 run {rid}「{run.get('name')}」：可执行 {len(cases)}，跳过 {len(skipped)}"
        f"（runner {cfg.runner_id}）")
    for s in skipped:
        log(f"  - 跳过 case {s['id']}：{s['reason']}")

    if not base_url:
        _finish(platform, rid, "failed", "项目没有配环境 base_url")
        log("  ✗ 没有 base_url，已标 failed")
        return

    headers, account, err = build_headers(platform, run["project_id"], claim.get("auth"),
                                          base_url, cfg.request_timeout, cfg.verify_ssl)
    if err:
        _finish(platform, rid, "failed", err)
        log(f"  ✗ 鉴权失败，已标 failed：{err}")
        return
    if not claim.get("auth"):
        log("  ! 项目没配 auth，只跑不需要鉴权的用例")

    counts = {"pass": 0, "fail": 0, "blocked": 0}
    # UI 用单独的 base_url：API 为了绕过出网丢包常走内网 IP 直连，
    # 但页面必须按域名加载（静态资源、Cookie 域、企微 JSAPI 都跟域名绑着）。
    ui_base_url = (variables.get("uiBaseUrl") or base_url).strip()
    browser = None
    if _needs_ui(cases):
        ok, why = browser_mod.available()
        if not ok:
            _finish(platform, rid, "failed", why)
            log(f"  ✗ {why}")
            return
        try:
            browser = browser_mod.Session(
                ui_base_url,
                timeout_ms=cfg.ui_timeout_ms,
                headless=cfg.headless,
                ignore_https_errors=not cfg.verify_ssl,
            ).open()
            log(f"  浏览器已启动：{ui_base_url}（headless={cfg.headless}）")
        except browser_mod.UiError as exc:
            _finish(platform, rid, "failed", str(exc)[:300])
            log(f"  ✗ 浏览器启动失败：{exc}")
            return

    shot_dir = os.path.abspath(cfg.shot_dir)
    try:
        for case in cases:
            try:
                result = execute_case(platform, rid, run["project_id"], case,
                                      base_url, headers, cfg.request_timeout, account,
                                      cfg.verify_ssl, variables, browser, shot_dir)
            except ApiError as exc:
                log(f"  ✗ case {case['id']} 回填失败：{exc}")
                continue
            except Exception as exc:                  # noqa: BLE001 单条崩溃不拖垮整轮
                log(f"  ✗ case {case['id']} 执行崩溃：{exc}")
                traceback.print_exc()
                continue
            counts[result["result"]] += 1
            log(f"  · case {case['id']} {result['result']}（{result['steps']} 步，"
                f"execution {result['execution_id']}）")
    finally:
        if browser:
            browser.close()
            log("  浏览器已关闭")

    executed = sum(counts.values())
    if cases and executed == 0:
        _finish(platform, rid, "failed", "所有用例都没能回填执行结果")
        log("  ✗ 一条都没回填成功，已标 failed")
        return
    fin = _finish(platform, rid, "done")
    if fin:
        log(f"  ✓ run {rid} 完成：{fin['summary']}")


def main():
    cfg = Config()
    problem = cfg.problems()
    if problem:
        print(f"配置错误：{problem}", file=sys.stderr)
        return 2
    _install_console_close_guard()   # Windows 关窗 → 自发送 BREAK → 走中断收尾
    platform = Platform(cfg.platform_url, cfg.api_token, cfg.request_timeout)
    log(f"runner 启动：{cfg.platform_url}，轮询间隔 {cfg.poll_seconds}s"
        f"，身份 {cfg.runner_id}"
        + (f"，只处理项目 {cfg.project_id}" if cfg.project_id else ""))
    while True:
        try:
            runs = platform.queued_runs(cfg.project_id or None)
        except ApiError as exc:
            log(f"取队列失败：{exc}")
            runs = []
        except Exception as exc:                      # noqa: BLE001 网络抖动不致命
            log(f"平台不可达：{exc}")
            runs = []
        for row in runs:
            process(platform, row, cfg)
        if cfg.run_once:
            break
        time.sleep(cfg.poll_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
