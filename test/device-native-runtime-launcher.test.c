#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

static int test_memorystatus_control(uint32_t command, int32_t pid,
    uint32_t flags, void *buffer, size_t buffersize);
static int test_execv(const char *path, char *const arguments[]);

#define NATIVE_RUNTIME_MEMSTATUS_CONTROL test_memorystatus_control
#define NATIVE_RUNTIME_EXECV test_execv
#define main native_runtime_launcher_main
#include "../bridge/device/native-runtime-launcher/main.c"
#undef main

static int memory_status_error;
static int fail_get;
static int mismatch_get;
static int exec_error;
static int set_calls;
static int get_calls;
static int exec_calls;
static memorystatus_memlimit_properties_t stored;
static const char *exec_path;
static char **exec_arguments;

static int
test_memorystatus_control(uint32_t command, int32_t pid, uint32_t flags,
    void *buffer, size_t buffersize)
{
  assert(pid == getpid());
  assert(flags == 0);
  assert(buffersize == sizeof(stored));
  if (command == MEMORYSTATUS_CMD_SET_MEMLIMIT_PROPERTIES) {
    set_calls++;
    if (memory_status_error != 0) {
      errno = memory_status_error;
      return -1;
    }
    memcpy(&stored, buffer, sizeof(stored));
    return 0;
  }
  assert(command == MEMORYSTATUS_CMD_GET_MEMLIMIT_PROPERTIES);
  get_calls++;
  if (fail_get) {
    errno = EIO;
    return -1;
  }
  if (mismatch_get)
    stored.memlimit_inactive--;
  memcpy(buffer, &stored, sizeof(stored));
  return 0;
}

static int
test_execv(const char *path, char *const arguments[])
{
  exec_calls++;
  exec_path = path;
  exec_arguments = (char **) arguments;
  errno = exec_error;
  return -1;
}

static void
reset_state(void)
{
  memory_status_error = 0;
  fail_get = 0;
  mismatch_get = 0;
  exec_error = ENOENT;
  set_calls = 0;
  get_calls = 0;
  exec_calls = 0;
  memset(&stored, 0, sizeof(stored));
  exec_path = NULL;
  exec_arguments = NULL;
}

int
main(void)
{
  char *relative[] = { "launcher", "python3", "runtime.py", NULL };
  char *environment[] = { "launcher", "/var/jb/usr/bin/env", "python3", NULL };
  char *valid[] = { "launcher", "/var/jb/usr/bin/python3", "runtime.py",
      "config.json", NULL };

  reset_state();
  assert(native_runtime_launcher_main(3, relative) == 64);
  assert(set_calls == 0 && get_calls == 0 && exec_calls == 0);

  reset_state();
  assert(native_runtime_launcher_main(3, environment) == 64);
  assert(set_calls == 0 && get_calls == 0 && exec_calls == 0);

  reset_state();
  memory_status_error = EPERM;
  assert(native_runtime_launcher_main(4, valid) == 71);
  assert(set_calls == 1 && get_calls == 0 && exec_calls == 0);

  reset_state();
  fail_get = 1;
  assert(native_runtime_launcher_main(4, valid) == 72);
  assert(set_calls == 1 && get_calls == 1 && exec_calls == 0);

  reset_state();
  mismatch_get = 1;
  assert(native_runtime_launcher_main(4, valid) == 73);
  assert(set_calls == 1 && get_calls == 1 && exec_calls == 0);

  reset_state();
  assert(native_runtime_launcher_main(4, valid) == 74);
  assert(set_calls == 1 && get_calls == 1 && exec_calls == 1);
  assert(stored.memlimit_active == 64 && stored.memlimit_inactive == 64);
  assert(stored.memlimit_active_attr == MEMORYSTATUS_MEMLIMIT_ATTR_FATAL);
  assert(stored.memlimit_inactive_attr == MEMORYSTATUS_MEMLIMIT_ATTR_FATAL);
  assert(strcmp(exec_path, valid[1]) == 0);
  assert(exec_arguments == &valid[1]);
  assert(strcmp(exec_arguments[1], "runtime.py") == 0);
  assert(strcmp(exec_arguments[2], "config.json") == 0);

  puts("native runtime launcher tests passed");
  return 0;
}
