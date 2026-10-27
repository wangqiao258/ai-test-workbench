# 协作约定（AI 与人）

> 只写"怎么干活"，业务规则仍只写在 `docs/ai_guide.md` 与 `docs/ai_guide_reference.md`。

## 命令输出必须能看见进度

长命令卡成一片空白，几乎都不是跑得慢，而是输出被攒住了。三条禁令：

1. **不接 `| Out-String`**。它是聚合型 cmdlet，会把整条命令的输出攒到结束才吐一次，
   终端在跑完之前全程空白。同理少接 `Format-Table`、`Out-GridView`。
2. **Python 一律加 `-u`**（或 `$env:PYTHONUNBUFFERED='1'`）。输出进管道时默认块缓冲，
   进度会攒到 8KB 才刷。
3. **中文环境带 UTF-8**：`$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`。
   少了它，直跑测试脚本会乱码；IDE/杀软的删除补丁也可能抛 gbk 解码异常。

## 跑测试

在 `ai-test-platform/` 下：

```powershell
.\.venv\Scripts\python.exe -u tests/run_all.py -k test_   # 先跑快的 5 个，约 3 秒
.\.venv\Scripts\python.exe -u tests/run_all.py            # 全量 26 个，约 1 分钟
```

- `run_all.py` 自己会刷缓冲、报心跳：每个脚本打 `RUN`，静默 10 秒打一行心跳，
  结束打 `PASS/FAIL`。**默认不转发脚本全文**（避免刷屏），要看得加 `-v`。
- 只跑相关的：`-k bug`；遇错即停：`--stop`；先看清单：`--list`。
- 怀疑卡死时用 `--timeout 60` 快速失败，别用默认 300 秒干等。
- 单脚本直接跑（排除干扰）时也要 `-u`，并带上两个 UTF-8 环境变量。

## 长任务

预计超过 1 分钟、又必须整段跑完的，落日志再轮询，不要盯着一个阻塞调用：

```powershell
Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList '-u','tests/run_all.py' `
  -RedirectStandardOutput tests/_run.log -RedirectStandardError tests/_run.err -NoNewWindow
Get-Content tests/_run.log -Tail 20     # 隔一会儿再看，不用 -Wait
```

日志文件用完删掉，别提交。
