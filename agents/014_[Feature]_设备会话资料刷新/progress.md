# 操作记录

- 初始 worktree 位于已提交 `feature/group-rendering`，HEAD `3ff3d48`，只有既有未跟踪 `work/`；保留该目录。
- 已切到 `feature/profile-refresh` 独立任务分支。
- 读取 Worker profile PUT 校验和现有 `Relay.headers()` / `Relay.request()` 实现；未修改 `device_runtime.py`。
- 新增 `conversation_profiles.py`：整批最多 20 项、先验证后请求，按 Worker header 名称发送 UTF-8 percent-encoded 文本和规范时间戳；使用现有 Relay 认证/产品请求头，直接走 `urllib` NoRedirect、20 秒 timeout、1 MiB响应界限，PUT 空 body 并显式 `Content-Length: 0`。
- 新增根目录 Python 行为测试，覆盖 UTF-8编码、profile 规则校验、失败传播停止后续请求、redirect拒绝、响应体上限与 Worker 拒绝响应。
- 首轮测试发现空 bytes 不会由 urllib 自动生成 `Content-Length: 0`；显式加入后请求契约测试通过。
- `python test/test_conversation_profiles.py -v` 六项通过；`python test/test_device_runtime.py` 32项通过（1项跳过）；`py_compile` 通过。
- 完整根目录 Python 测试发现运行 `python -m unittest discover -s test -p 'test_*.py'` 共 46 项通过、1 项跳过。
- 已提交本地分支，提交 `d72865a`；未推送或合并。
