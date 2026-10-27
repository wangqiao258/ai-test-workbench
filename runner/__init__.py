"""执行引擎（P1）：轮询 queued 的 run → 认领 → 逐条逐步执行 → 回填。

只通过平台公开 API 读写，不 import api/ / db；断言引擎复用 core/asserts.py
（纯函数、无 IO），保证"怎么算通过"两边永远同一套规则。
"""
