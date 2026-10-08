# 进度

- 已确认旧备份行的 sender ID 会覆盖重放输入，并且重复消息分支不更新规范消息 sender 字段。
- 已实现 sender 字段的有界重放更新，并在消息及备份 conversation 校验通过后落库。
- 已补旧 null、旧 alias、无 sender、跨 conversation 冲突、正文/时间/附件保留与消息计数测试。
- `node --test test/worker-media-backfill.test.mjs` 通过。
- `node --test test/worker-*.test.mjs` 通过（4 项）。
