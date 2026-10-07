#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#define MEMORYSTATUS_CMD_SET_MEMLIMIT_PROPERTIES 7
#define MEMORYSTATUS_CMD_GET_MEMLIMIT_PROPERTIES 8
#define MEMORYSTATUS_MEMLIMIT_ATTR_FATAL 1
#define RUNTIME_MEMORY_LIMIT_MB 64

typedef struct {
  int32_t memlimit_active;
  uint32_t memlimit_active_attr;
  int32_t memlimit_inactive;
  uint32_t memlimit_inactive_attr;
} memorystatus_memlimit_properties_t;

#ifndef NATIVE_RUNTIME_MEMSTATUS_CONTROL
extern int memorystatus_control(uint32_t command, int32_t pid, uint32_t flags,
    void *buffer, size_t buffersize);
#define NATIVE_RUNTIME_MEMSTATUS_CONTROL memorystatus_control
#endif

#ifndef NATIVE_RUNTIME_EXECV
#define NATIVE_RUNTIME_EXECV execv
#endif

static int
is_forbidden_program(const char *path)
{
  static const char *const forbidden[] = {
    "env", "sh", "bash", "zsh", "dash", "ash", "busybox", NULL
  };
  const char *basename = strrchr(path, '/');
  basename = basename != NULL ? basename + 1 : path;

  for (size_t i = 0; forbidden[i] != NULL; i++) {
    if (strcmp(basename, forbidden[i]) == 0)
      return 1;
  }
  return 0;
}

static void
report_error(const char *operation, int error)
{
  fprintf(stderr, "native-runtime-launcher: %s failed (%d)\n", operation,
      error);
}

int
main(int argc, char **argv)
{
  if (argc < 2 || argv[1] == NULL || argv[1][0] != '/' ||
      is_forbidden_program(argv[1])) {
    report_error("arguments", EINVAL);
    return 64;
  }

  memorystatus_memlimit_properties_t requested = {
    .memlimit_active = RUNTIME_MEMORY_LIMIT_MB,
    .memlimit_active_attr = MEMORYSTATUS_MEMLIMIT_ATTR_FATAL,
    .memlimit_inactive = RUNTIME_MEMORY_LIMIT_MB,
    .memlimit_inactive_attr = MEMORYSTATUS_MEMLIMIT_ATTR_FATAL
  };
  if (NATIVE_RUNTIME_MEMSTATUS_CONTROL(
          MEMORYSTATUS_CMD_SET_MEMLIMIT_PROPERTIES, getpid(), 0,
          &requested, sizeof(requested)) != 0) {
    int error = errno;
    report_error("set_memory_limit", error);
    return 71;
  }

  memorystatus_memlimit_properties_t actual = {0};
  if (NATIVE_RUNTIME_MEMSTATUS_CONTROL(
          MEMORYSTATUS_CMD_GET_MEMLIMIT_PROPERTIES, getpid(), 0,
          &actual, sizeof(actual)) != 0) {
    int error = errno;
    report_error("verify_memory_limit", error);
    return 72;
  }
  if (requested.memlimit_active != actual.memlimit_active ||
      requested.memlimit_active_attr != actual.memlimit_active_attr ||
      requested.memlimit_inactive != actual.memlimit_inactive ||
      requested.memlimit_inactive_attr != actual.memlimit_inactive_attr) {
    report_error("verify_memory_limit", EINVAL);
    return 73;
  }

  NATIVE_RUNTIME_EXECV(argv[1], &argv[1]);
  int error = errno;
  report_error("exec", error);
  return 74;
}
