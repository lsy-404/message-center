# Progress

- 阅读 `agents/project.md`、任务索引、设备运行器契约与既有 cursor/outbox 实现。
- 静态检查公开 TS device adapter 的 cursor 提交边界以及私有 QQ/微信分页实现；没有连接设备或执行适配器。
- 创建独立分支 `feature/device-cursor`。
- 新增纯Python状态机 `source_cursor.py`：明确首轮≤20条baseline事件；后续冻结high-water、剔除inclusive anchor、逐页outbox推进，直至旧head后才提交新head；期间新到消息留到下一sweep。
- 添加根目录合成测试，覆盖首次baseline、空baseline、跨页追旧head、扫描期间新head、重复/无进展/缺旧head/超预算与短不完整页失败。
- 设备运行器和游标测试总计32项：31通过、1项POSIX-only跳过；`git diff --check`通过。状态机只约束协议，不证明native API本身无遗漏。
