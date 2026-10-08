# 进度

- 已从 `main` 创建干净独立分支 `feature/heartbeat-persistence`。
- 已完成静态调用链检查；未连接设备、Worker 或云端。
- 修改 `bridge/device-runtime/device_runtime.py`：为心跳增加独立 connector 退避，15/30/60 秒封顶；scan/command 退避不再抑制 heartbeat，heartbeat 请求失败也不改变业务操作退避。
- 修改 `test/test_device_runtime.py`：覆盖 scan 异常时持续发送 offline 心跳、网络心跳错误独立退避与成功复位、指数退避封顶。
- `python -m unittest discover -s test -p test_device_runtime.py -v`：45 项通过，1 项 POSIX-only 跳过。
- `python -m unittest discover -s test -v`：68 项通过，1 项 POSIX-only 跳过。
- 本地提交完成；不推送、不部署。
