# 发现
- 用户确认 QQ 保持前台，要求完成采集。
- 设备接收器仍运行，已跟踪10个会话，outbox=0，错误日志为空；云端在线连接器=0。
- 暂停专属接收job后独立scan在18.32秒失败，类别native-helper-failed；finally已恢复接收服务。
- outbox为空不足以证明会话发现集合已全部采集。必须核对发现数、未初始化数、pending sweep和changed计数。
- 串行隔离：QQ空脚本也在attach阶段5/8/12秒超时；较长窗口25.2秒返回attach_failed。锁屏Darwin通知查询成功、state=0。uiopen并未恢复连接。
- 同一工具对本次创建的sleep对照进程附加0.51秒成功；同版host客户端对QQ返回TransportError timeout。说明故障与QQ的server附加状态相关，而不是消息脚本或整个设备控制面失效。
- 只读task_for_pid返回5，未尝试新增权限。netstat未安装，未据此推断活动连接数。
- 精确核验现有控制服务二进制后重载本项目使用的控制服务；QQ进程未变化。随后空attach1.36秒成功，真实scan1.4秒成功。
- 恢复后的发现集合17个会话，其中未初始化6、pending0，说明outbox空和tracked10不足以判定完成。正使用原有Relay原子队列收尾，不绕过预算或保存确认。

- 收尾操作用时77.83秒，6次有界扫描产生93条事件；连同已有队列5条，共98条逐条确认新入库，0条去重、0条抑制。终点tracked17、pending sweep0、outbox0、more=false。
- 独立终点复核：发现17、uninitialized0、pending0、changed0，消息数0、more=false。此完成范围是当前发现集合的基线及增量，不是全量历史导入（每会话基线最多20条）。
- 常驻receiver恢复running，GET内存预算64/64 MB fatal，RSS21248 KiB，错误日志0；云端连接器online1，页面/资源均200，云端会话69。电脑中继仍Disabled。发送ledger0，本次没有发送动作。
- helper成功路径独立复核没有发现已报告cleanup错误被当成成功；不添加未经证实的补丁或共享服务自动重载策略。
