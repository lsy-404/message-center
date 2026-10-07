# Native runtime launcher

This small iOS arm64 launcher sets and reads back a finite 64 MB active and inactive fatal memory limit for its own PID, then directly `execv`s the absolute executable in `argv[1]`, preserving its arguments. If the kernel rejects the request or returns different limits, it exits before starting Python. It accepts no target PID, does not invoke a shell or `/usr/bin/env`, and uses no private signing entitlement.

The launchd sample uses `/var/jb/usr/local/libexec/message-center/native-runtime-launcher` followed by the absolute Python path and runtime arguments. Install the launcher beside `native-frida-helper`. Do not enable the service until the target device confirms the syscall works and the limit remains 64/64 MB after Python has started; XNU's public sources do not guarantee that these values survive exec's task replacement. A 64 MB fatal limit will terminate the runtime if it reaches that footprint.

From the build artifact directory:

```sh
install_dir=/var/jb/usr/local/libexec/message-center
mkdir -p "$install_dir"
cp native-runtime-launcher "$install_dir/native-runtime-launcher"
chmod 755 "$install_dir/native-runtime-launcher"
```
