# 调研记录

[同步 Frida API 无法保证有界取消] -> 头文件提供连接、attach、创建脚本、load/unload、detach 与 manager close 的异步回调形式 -> 实现全程使用异步接口与 GCancellable；输入读取有单独 deadline，运行 deadline 后取消操作并顺序清理，清理 callback 超时则退出进程并标记清理未完成。

[Frida devkit 没有随包提供 license 文件] -> 本地归档仅含头文件、静态库和示例 -> 构建 workflow 从对应上游 tag 取 COPYING，并在 artifact 中保留。

[目标运行依赖边界] -> 已有 Python 环境承担持久队列与 HTTPS，Frida server 监听本机 loopback -> helper 只负责单次授权脚本调用，不启动后台服务，也不承载队列或网络投递。

[原子结果契约] -> Frida `send` envelope 使用 JSON -> Foundation NSJSONSerialization 解析 envelope 并重新序列化 payload；stdout 只在调用结束输出一个 JSON 对象，Frida 日志和错误细节不输出。

[本机无法验证 iOS 链接结果] -> 当前 Windows 工作环境没有 Apple SDK、xcrun 或 clang -> 由窄路径 push/manual workflow 在 macOS runner 上执行原生链接与签名检查；设备端安装/调用仍需后续单独验证。

[异步 load 期间可连续收到 send] -> 首个 send 尚未触发卸载时，后续 send 可能到达并替换结果缓冲区 -> 锁存首个有效 payload，忽略之后所有 send；限制 payload 到 1 MiB 减 4 KiB 并对最终序列化响应再次设限。

[本机没有 workflow YAML linter] -> `actionlint`/`yamllint` 不在当前环境，Python 也未安装 YAML 模块 -> 按现有 workflow 结构复核 trigger、权限、SDK、静态链接参数、签名与 artifact 步骤；真实编译检查待 macOS runner。

[首个 iOS 构建成功但设备启动立即 SIGKILL] -> 产物静态检查显示 arm64 Mach-O、iOS 15.0 最低版本、SDK 18.5、有效 LC_MAIN 与 cryptid=0；两个 CodeDirectory 的 flags 均为 0，而 workflow 只调用 `ldid -S` -> 改为 `ldid -Cadhoc -S` 并在构建时检查每个嵌入 CodeDirectory 都带 `CS_ADHOC` (`0x2`)；这为下一轮设备验证提供可核查的签名差异，但尚不能断言该差异就是设备 SIGKILL 的根因。

[ad hoc artifact 在原安装位置立即 SIGKILL] -> 相同 SHA-256 的二进制放在 `/var/jb/usr/local/libexec/message-center` 后可启动并返回 `invalid_arguments`，在 `/var/mobile/Library` 下则在进入 main 前 SIGKILL -> 将可执行程序与适配器状态/数据库目录分开：helper 安装在 jailbreak 程序目录，持久状态继续留在 `/var/mobile/Library/`；此路径对照证明标准程序目录可执行，不推断更具体的内核策略原因。

[签名页哈希可能与传输后二进制不一致] -> 对新 artifact 的 SHA-1 与 SHA-256 CodeDirectory 均逐页重算，5,497 个 code slots 全部匹配，签名 blob 无尾随截断 -> 页面哈希/传输损坏不是当前设备启动差异的解释；已停止增加签名或 linker 变体。
