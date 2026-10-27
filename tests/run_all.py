"""一键跑完 tests/ 下的验证脚本（各自用副本库，不碰 data/app.db）。

用法（在 ai-test-platform 目录下）：
    python tests/run_all.py             # 全部
    python tests/run_all.py -k bug      # 只跑文件名含 bug 的
    python tests/run_all.py --stop      # 第一个失败就停
    python tests/run_all.py --list      # 只列出会跑哪些
    python tests/run_all.py -v          # 实时转发每个脚本的输出（默认不转发）

每个脚本都是独立进程：自己复制 app.db 到 data/_xxx.db，跑完自己删；一个失败不影响
后面的脚本，最后汇总。退出码 = 有没有失败（CI 或部署脚本里可直接用）。
依赖 runner 环境的脚本（e2e_runner 要 requests）在平台 venv 里缺包时显示 SKIP，不算失败。

进度是流式的：脚本一启动就打 RUN 行，静默超过 --beat 秒打一行心跳，结束打 PASS/FAIL，
所以任何时刻最多等 --beat 秒就有新输出；默认不转发子进程全文（避免刷屏），要看得加 -v。
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(BASE, "tests")
DATA = os.path.join(BASE, "data")

# 只跑验证脚本：test_* / verify_*，外加两个有专门名字的（冒烟、runner 端到端）。
# 新加脚本只要按前缀命名就会被自动收进来，不需要改这里。
PREFIXES = ("test_", "verify_")
EXTRAS = ("smoke_api.py", "e2e_runner.py")
SKIP = {"run_all.py"}
TAIL = 25
BEAT = 10          # 静默这么多秒就打一行心跳，保证屏幕不会长时间空白

# 依赖 runner 环境的脚本：平台 venv 里没有这些包时跳过，不算失败
# （e2e_runner 真的起 runner 子进程，需要 requests）
OPTIONAL_DEPS = {"e2e_runner.py": ("requests",)}


def missing_deps(name):
    return [d for d in OPTIONAL_DEPS.get(name, ())
            if importlib.util.find_spec(d) is None]


def discover(keyword=""):
    names = []
    for f in sorted(os.listdir(TESTS)):
        if not f.endswith(".py") or f in SKIP:
            continue
        if not (f.startswith(PREFIXES) or f in EXTRAS):
            continue
        if keyword and keyword.lower() not in f.lower():
            continue
        names.append(f)

    def rank(n):
        # 快的在前：纯单测 → 冒烟 → 页面级 → e2e（起两个端口，最慢）
        if n.startswith("test_"):
            return 0
        if n == "smoke_api.py":
            return 1
        if n == "e2e_runner.py":
            return 3
        return 2

    return sorted(names, key=lambda n: (rank(n), n))


def run_one(name, timeout, verbose=False, beat=BEAT):
    """流式跑一个脚本，返回 (是否通过, 输出全文, 耗时秒, 是否超时)。

    不用 subprocess.run(capture_output)：那样子进程输出全被吞掉，整轮跑完才见天日。
    这里用 Popen 边跑边收，静默超时打心跳，超时由 watchdog 线程 kill。
    """
    # UTF-8 模式必须显式带上：脚本里的中文输出 + IDE/杀软的删除补丁都靠它避坑
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               PYTHONUTF8="1")
    started = time.time()
    state = {"done": False, "timeout": False, "last": started}
    p = subprocess.Popen(
        [sys.executable, "-u", os.path.join("tests", name)],
        cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env, bufsize=1,
    )

    def killer():
        state["timeout"] = True
        try:
            p.kill()
        except OSError:
            pass

    def beater():
        while not state["done"]:
            time.sleep(1)
            if state["done"] or not beat:
                continue
            idle = time.time() - state["last"]
            if idle >= beat:
                state["last"] = time.time()      # 心跳本身算一次输出，别每秒刷
                print(f"        .. {name} 静默 {idle:.0f}s"
                      f"（累计 {time.time() - started:.0f}s）", flush=True)

    timer = threading.Timer(timeout, killer)
    timer.daemon = True
    timer.start()
    threading.Thread(target=beater, daemon=True).start()

    lines = []
    try:
        for line in p.stdout:
            text = line.rstrip("\r\n")
            lines.append(text)
            if verbose:
                # 只有真往屏幕上打了才算"有进度"，否则心跳会被子进程的沉默输出刷掉
                state["last"] = time.time()
                print("      | " + text, flush=True)
    finally:
        state["done"] = True
        timer.cancel()
        try:
            p.stdout.close()
        except OSError:
            pass

    p.wait()
    sec = time.time() - started
    out = "\n".join(lines)
    return (not state["timeout"]) and p.returncode == 0, out, sec, state["timeout"]


_QUIET_DELETE = {"on": False}


def _silence_shim_noise():
    """IDE/安全软件会把 os 的删除函数补成"移回收站"，那个补丁用 locale 解码子进程
    输出，中文 Windows（gbk）下必抛 UnicodeDecodeError。那是补丁自己的 bug，
    只在清理残留时出现，不该让它冒充测试失败。
    """
    base = threading.excepthook

    def hook(args):
        if (_QUIET_DELETE["on"] and isinstance(args.exc_value, UnicodeDecodeError)
                and args.thread is not None
                and args.thread.name.endswith("(_readerthread)")):
            return
        base(args)

    threading.excepthook = hook


def _rmtree(path):
    """自己删目录树，不走 shutil.rmtree。

    IDE/杀软常把 shutil.rmtree 打补丁改成"移回收站"，这里用 os.walk 真删。
    （补丁对 os.remove/os.rmdir 也生效，编码噪音由 _silence_shim_noise 兜住。）
    """
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except OSError:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def clean_leftovers():
    """脚本崩了会留下副本库/临时上传目录，统一清掉（只动 data/_* 前缀）。"""
    n = 0
    if not os.path.isdir(DATA):
        return 0
    _QUIET_DELETE["on"] = True      # 删除期间的补丁噪音不往终端抛
    for name in os.listdir(DATA):
        if not name.startswith("_"):
            continue
        if not (name.endswith((".db", ".db-wal", ".db-shm")) or "uploads" in name):
            continue
        p = os.path.join(DATA, name)
        if os.path.isdir(p):
            _rmtree(p)
        else:
            try:
                os.remove(p)
            except OSError:
                continue
        n += 1
    return n


def main():
    # 输出被常到管道/文件时（PowerShell 重定向、CI）Python 默认块缓冲，进度会攒着不出来
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    _silence_shim_noise()

    ap = argparse.ArgumentParser(description="顺序跑 tests/ 下的所有验证脚本")
    ap.add_argument("-k", "--keyword", default="", help="只跑文件名含该子串的脚本")
    ap.add_argument("--stop", action="store_true", help="第一个失败就停")
    ap.add_argument("--list", action="store_true", help="只列出会跑哪些脚本")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="实时转发每个脚本的输出（默认只报开始/心跳/结果）")
    ap.add_argument("--timeout", type=int, default=300, help="单个脚本超时秒数（默认 300）")
    ap.add_argument("--beat", type=int, default=BEAT,
                    help=f"静默几秒打一行心跳，0 关闭（默认 {BEAT}）")
    args = ap.parse_args()

    names = discover(args.keyword)
    if not names:
        print("没有匹配的脚本" + (f"（-k {args.keyword}）" if args.keyword else ""))
        return 1
    if args.list:
        for n in names:
            print(n)
        return 0

    print(f"== 跑 {len(names)} 个脚本（每个独立进程 + 副本库）=="
          f"  {args.beat}s 无输出即打心跳，-v 看全量输出", flush=True)
    failed, skipped, elapsed_all = [], [], 0.0
    for i, name in enumerate(names, 1):
        miss = missing_deps(name)
        if miss:
            skipped.append(name)
            print(f"SKIP  {name:<34} 缺 {', '.join(miss)}"
                  f"（pip install -r runner/requirements.txt 后自动跑）"
                  f"  [{i}/{len(names)}]", flush=True)
            continue
        print(f"RUN   {name:<34} [{i}/{len(names)}]", flush=True)
        ok, out, sec, timed_out = run_one(name, args.timeout, args.verbose, args.beat)
        elapsed_all += sec
        print(f"{'PASS' if ok else 'FAIL'}  {name:<34} {sec:6.1f}s  [{i}/{len(names)}]",
              flush=True)
        if not ok:
            failed.append(name)
            if not args.verbose:          # 已经实时转发过就不重打，免得刷屏
                tail = [ln for ln in out.strip().splitlines() if ln.strip()][-TAIL:]
                for ln in tail:
                    print("      " + ln.replace("\t", "  "), flush=True)
            if timed_out:
                print(f"      [run_all] 超时（>{args.timeout}s），已终止", flush=True)
            if args.stop:
                print("\n--stop：提前结束")
                break

    left = clean_leftovers()
    if left:
        print(f"已清理 {left} 个测试残留（data/_*）")
    passed = len(names) - len(failed) - len(skipped)
    print(f"\n== {len(names)} 个脚本：{passed} 通过 / {len(failed)} 失败"
          f"{' / %d 跳过' % len(skipped) if skipped else ''}，用时 {elapsed_all:.0f}s ==",
          flush=True)
    if failed:
        print("失败：" + "、".join(failed))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
