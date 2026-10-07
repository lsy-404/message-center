# 调研记录

[同步 Frida API 无法保证有界取消] -> 头文件提供连接、attach、创建脚本、load/unload、detach 与 manager close 的异步回调形式 -> 实现全程使用异步接口与 GCancellable；输入读取有单独 deadline，运行 deadline 后取消操作并顺序清理，清理 callback 超时则退出进程并标记清理未完成。

[Frida devkit 没有随包提供 license 文件] -> 本地归档仅含头文件、静态库和示例 -> 构建 workflow 从对应上游 tag 取 COPYING，并在 artifact 中保留。

[目标运行依赖边界] -> 已有 Python 环境承担持久队列与 HTTPS，Frida server 监听本机 loopback -> helper 只负责单次授权脚本调用，不启动后台服务，也不承载队列或网络投递。

[原子结果契约] -> Frida `send` envelope 使用 JSON -> Foundation NSJSONSerialization 解析 envelope 并重新序列化 payload；stdout 只在调用结束输出一个 JSON 对象，Frida 日志和错误细节不输出。

[本机无法验证 iOS 链接结果] -> 当前 Windows 工作环境没有 Apple SDK、xcrun 或 clang -> 由窄路径 push/manual workflow 在 macOS runner 上执行原生链接与签名检查；设备端安装/调用仍需后续单独验证。
