#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>

#include "frida-core.h"
#include "binary-output.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define MAX_INPUT_BYTES (1024 * 1024)
#define MAX_RESULT_BYTES (MAX_INPUT_BYTES - 4096)
#define DEFAULT_TIMEOUT_MS 30000
#define MAX_TIMEOUT_MS 120000
#define CLEANUP_TIMEOUT_MS 5000
#define CANCEL_GRACE_MS 3000

typedef struct {
  GMainLoop *loop;
  GCancellable *operation_cancel;
  GCancellable *cleanup_cancel;
  FridaDeviceManager *manager;
  FridaDevice *device;
  FridaSession *session;
  FridaScript *script;
  gchar *script_source;
  gchar *result_json;
  BinaryOutput binary_output;
  guint64 binary_byte_count;
  const gchar *stage;
  const gchar *error_stage;
  const gchar *error_code;
  const gchar *response_error_code;
  const gchar *cleanup_code;
  guint timeout_source;
  guint cleanup_timeout_source;
  guint force_source;
  guint pid;
  gboolean operation_in_flight;
  gboolean cleanup_started;
  gboolean load_started;
  gboolean result_received;
  gboolean eternalize_requested;
  gboolean script_eternalized;
  gboolean binary_written;
  gboolean timed_out;
  gboolean hard_timeout;
} Helper;

static void start_cleanup(Helper *helper);
static void fail(Helper *helper, const gchar *stage, const gchar *code);

static void
reject_response(Helper *helper, const gchar *code)
{
  helper->response_error_code = code;
  fail(helper, "result", code);
  if (helper->operation_in_flight)
    g_cancellable_cancel(helper->operation_cancel);
  else
    start_cleanup(helper);
}

static gboolean
parse_binary_byte_count(id value, guint64 maximum, guint64 *count)
{
  if (![value isKindOfClass:[NSNumber class]] || count == NULL ||
      CFGetTypeID((__bridge CFTypeRef) value) == CFBooleanGetTypeID())
    return FALSE;
  double numeric = [value doubleValue];
  if (!isfinite(numeric) || numeric < 1 || numeric > (double) maximum ||
      floor(numeric) != numeric)
    return FALSE;
  *count = [value unsignedLongLongValue];
  return *count >= 1 && *count <= maximum;
}

static void
set_stage(Helper *helper, const gchar *stage)
{
  helper->stage = stage;
}

static void
fail(Helper *helper, const gchar *stage, const gchar *code)
{
  if (helper->error_code == NULL) {
    helper->error_stage = stage;
    helper->error_code = code;
  }
}

static void
remove_source(guint *source_id)
{
  if (*source_id != 0) {
    g_source_remove(*source_id);
    *source_id = 0;
  }
}

static void
finish(Helper *helper)
{
  remove_source(&helper->timeout_source);
  remove_source(&helper->cleanup_timeout_source);
  remove_source(&helper->force_source);
  if (g_main_loop_is_running(helper->loop))
    g_main_loop_quit(helper->loop);
}

static gboolean
force_finish(gpointer user_data)
{
  Helper *helper = user_data;
  helper->force_source = 0;
  helper->hard_timeout = TRUE;
  if (helper->cleanup_code == NULL)
    helper->cleanup_code = "cleanup_timeout";
  finish(helper);
  return G_SOURCE_REMOVE;
}

static gboolean
on_cleanup_timeout(gpointer user_data)
{
  Helper *helper = user_data;
  helper->cleanup_timeout_source = 0;
  if (helper->cleanup_code == NULL)
    helper->cleanup_code = "cleanup_timeout";
  g_cancellable_cancel(helper->cleanup_cancel);
  helper->force_source = g_timeout_add(CANCEL_GRACE_MS, force_finish, helper);
  return G_SOURCE_REMOVE;
}

static void
close_manager(Helper *helper);

static void
on_manager_closed(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  frida_device_manager_close_finish(FRIDA_DEVICE_MANAGER(source), result, &error);
  if (error != NULL) {
    if (helper->cleanup_code == NULL)
      helper->cleanup_code = "manager_close_failed";
    g_error_free(error);
  }
  finish(helper);
}

static void
close_manager(Helper *helper)
{
  if (helper->manager == NULL) {
    finish(helper);
    return;
  }
  set_stage(helper, "close");
  frida_device_manager_close(helper->manager, helper->cleanup_cancel,
      on_manager_closed, helper);
}

static void
on_session_detached(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  frida_session_detach_finish(FRIDA_SESSION(source), result, &error);
  if (error != NULL) {
    if (helper->cleanup_code == NULL)
      helper->cleanup_code = "detach_failed";
    g_error_free(error);
  }
  close_manager(helper);
}

static void
detach_session(Helper *helper)
{
  if (helper->session == NULL || frida_session_is_detached(helper->session)) {
    close_manager(helper);
    return;
  }
  set_stage(helper, "detach");
  frida_session_detach(helper->session, helper->cleanup_cancel,
      on_session_detached, helper);
}

static void
on_script_eternalized(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  helper->operation_in_flight = FALSE;
  frida_script_eternalize_finish(FRIDA_SCRIPT(source), result, &error);
  if (error != NULL) {
    fail(helper, "eternalize", "eternalize_failed");
    g_error_free(error);
    start_cleanup(helper);
    return;
  }
  helper->script_eternalized = TRUE;
  frida_script_post(helper->script,
      "{\"type\":\"native-helper-eternalized\"}", NULL);
  start_cleanup(helper);
}

static void
complete_script(Helper *helper)
{
  if (helper->eternalize_requested && helper->result_received &&
      helper->error_code == NULL && helper->script != NULL &&
      !helper->script_eternalized && !helper->cleanup_started) {
    set_stage(helper, "eternalize");
    helper->operation_in_flight = TRUE;
    frida_script_eternalize(helper->script, helper->operation_cancel,
        on_script_eternalized, helper);
    return;
  }
  start_cleanup(helper);
}

static void
on_script_unloaded(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  frida_script_unload_finish(FRIDA_SCRIPT(source), result, &error);
  if (error != NULL) {
    if (helper->cleanup_code == NULL)
      helper->cleanup_code = "unload_failed";
    g_error_free(error);
  }
  detach_session(helper);
}

static void
unload_script(Helper *helper)
{
  if (helper->script_eternalized) {
    detach_session(helper);
    return;
  }
  if (helper->script == NULL || !helper->load_started ||
      frida_script_is_destroyed(helper->script)) {
    detach_session(helper);
    return;
  }
  set_stage(helper, "unload");
  frida_script_unload(helper->script, helper->cleanup_cancel,
      on_script_unloaded, helper);
}

static void
start_cleanup(Helper *helper)
{
  if (helper->cleanup_started)
    return;
  helper->cleanup_started = TRUE;
  remove_source(&helper->timeout_source);
  remove_source(&helper->force_source);
  helper->cleanup_timeout_source = g_timeout_add(CLEANUP_TIMEOUT_MS,
      on_cleanup_timeout, helper);
  if (helper->script != NULL)
    unload_script(helper);
  else
    detach_session(helper);
}

static void
on_script_message(FridaScript *script, const gchar *message, GBytes *data,
    gpointer user_data)
{
  Helper *helper = user_data;
  gsize length;
  NSData *message_data;
  NSError *parse_error = nil;
  NSDictionary *envelope;
  NSString *type;

  (void) script;
  if (message == NULL)
    return;
  if (helper->result_received) {
    if (helper->binary_output.enabled) {
      fail(helper, "result", "duplicate_send");
      if (binary_output_reset(&helper->binary_output) != BINARY_OUTPUT_OK)
        helper->cleanup_code = "binary_output_reset_failed";
      helper->binary_written = FALSE;
      helper->binary_byte_count = 0;
      if (helper->operation_in_flight)
        g_cancellable_cancel(helper->operation_cancel);
      else
        start_cleanup(helper);
    }
    return;
  }
  if (helper->cleanup_started)
    return;

  length = strnlen(message, MAX_INPUT_BYTES + 1);
  if (length > MAX_INPUT_BYTES) {
    helper->response_error_code = "response_too_large";
    return;
  }

  message_data = [[NSData alloc] initWithBytes:message length:length];
  id parsed = [NSJSONSerialization JSONObjectWithData:message_data
      options:NSJSONReadingFragmentsAllowed error:&parse_error];
  if (![parsed isKindOfClass:[NSDictionary class]])
    return;
  envelope = (NSDictionary *) parsed;
  type = envelope[@"type"];
  if (![type isKindOfClass:[NSString class]])
    return;

  if ([type isEqualToString:@"send"]) {
    id payload = envelope[@"payload"];
    if (payload == nil) {
      reject_response(helper, "invalid_response");
      return;
    }
    guint64 declared_bytes = 0;
    gsize binary_length = data == NULL ? 0 : g_bytes_get_size(data);
    if (helper->binary_output.enabled) {
      id success_value = [payload isKindOfClass:[NSDictionary class]] ? payload[@"ok"] : nil;
      id byte_count_value = [payload isKindOfClass:[NSDictionary class]]
          ? payload[@"byteCount"] : nil;
      if (![success_value isKindOfClass:[NSNumber class]] ||
          CFGetTypeID((__bridge CFTypeRef) success_value) != CFBooleanGetTypeID() ||
          ![success_value boolValue] || data == NULL || binary_length == 0 ||
          !parse_binary_byte_count(byte_count_value,
              helper->binary_output.max_bytes, &declared_bytes) ||
          declared_bytes != binary_length) {
        reject_response(helper, "invalid_binary_response");
        return;
      }
    } else if (data != NULL) {
      reject_response(helper, "binary_output_not_enabled");
      return;
    }
    NSError *serialize_error = nil;
    NSData *payload_data = [NSJSONSerialization dataWithJSONObject:payload
        options:NSJSONWritingFragmentsAllowed error:&serialize_error];
    if (payload_data == nil) {
      reject_response(helper, "invalid_response");
    } else if (payload_data.length > MAX_RESULT_BYTES) {
      reject_response(helper, "response_too_large");
    } else {
      if (helper->binary_output.enabled) {
        gsize bytes_length = 0;
        gconstpointer bytes = g_bytes_get_data(data, &bytes_length);
        BinaryOutputStatus status = binary_output_write(&helper->binary_output,
            bytes, bytes_length);
        if (status != BINARY_OUTPUT_OK) {
          reject_response(helper, binary_output_status_name(status));
          return;
        }
        helper->binary_written = TRUE;
        helper->binary_byte_count = declared_bytes;
      }
      helper->result_json = g_strndup(payload_data.bytes, payload_data.length);
      helper->result_received = TRUE;
    }
    if (!helper->operation_in_flight)
      complete_script(helper);
  } else if ([type isEqualToString:@"error"]) {
    fail(helper, "script", "script_error");
    if (helper->operation_in_flight)
      g_cancellable_cancel(helper->operation_cancel);
    else
      start_cleanup(helper);
  }
}

static void
on_session_detached_signal(FridaSession *session, FridaSessionDetachReason reason,
    FridaCrash *crash, gpointer user_data)
{
  Helper *helper = user_data;
  (void) session;
  (void) reason;
  (void) crash;
  if (helper->cleanup_started)
    return;
  fail(helper, helper->stage, "session_detached");
  if (helper->operation_in_flight)
    g_cancellable_cancel(helper->operation_cancel);
  else
    start_cleanup(helper);
}

static void
on_script_loaded(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  helper->operation_in_flight = FALSE;
  frida_script_load_finish(FRIDA_SCRIPT(source), result, &error);
  if (error != NULL) {
    if (helper->error_code == NULL)
      fail(helper, "load", "load_failed");
    g_error_free(error);
    start_cleanup(helper);
  } else if (helper->result_received || helper->error_code != NULL) {
    complete_script(helper);
  } else {
    set_stage(helper, "await_result");
  }
}

static void
on_script_created(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  helper->operation_in_flight = FALSE;
  helper->script = frida_session_create_script_finish(FRIDA_SESSION(source),
      result, &error);
  g_clear_pointer(&helper->script_source, g_free);
  if (helper->timed_out || helper->error_code != NULL) {
    if (error != NULL)
      g_error_free(error);
    start_cleanup(helper);
    return;
  }
  if (error != NULL || helper->script == NULL) {
    fail(helper, "create_script", "script_create_failed");
    if (error != NULL)
      g_error_free(error);
    start_cleanup(helper);
    return;
  }

  g_signal_connect(helper->script, "message", G_CALLBACK(on_script_message), helper);
  set_stage(helper, "load");
  helper->load_started = TRUE;
  helper->operation_in_flight = TRUE;
  frida_script_load(helper->script, helper->operation_cancel,
      on_script_loaded, helper);
}

static void
on_session_attached(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  helper->operation_in_flight = FALSE;
  helper->session = frida_device_attach_finish(FRIDA_DEVICE(source), result, &error);
  if (helper->timed_out || helper->error_code != NULL) {
    if (error != NULL)
      g_error_free(error);
    start_cleanup(helper);
    return;
  }
  if (error != NULL || helper->session == NULL) {
    fail(helper, "attach", "attach_failed");
    if (error != NULL)
      g_error_free(error);
    start_cleanup(helper);
    return;
  }

  g_signal_connect(helper->session, "detached",
      G_CALLBACK(on_session_detached_signal), helper);
  FridaScriptOptions *options = frida_script_options_new();
  frida_script_options_set_name(options, "local-session");
  frida_script_options_set_runtime(options, FRIDA_SCRIPT_RUNTIME_QJS);
  set_stage(helper, "create_script");
  helper->operation_in_flight = TRUE;
  frida_session_create_script(helper->session, helper->script_source,
      options, helper->operation_cancel, on_script_created, helper);
  g_object_unref(options);
}

static void
on_device_connected(GObject *source, GAsyncResult *result, gpointer user_data)
{
  Helper *helper = user_data;
  GError *error = NULL;
  helper->operation_in_flight = FALSE;
  helper->device = frida_device_manager_add_remote_device_finish(
      FRIDA_DEVICE_MANAGER(source), result, &error);
  if (helper->timed_out || helper->error_code != NULL) {
    if (error != NULL)
      g_error_free(error);
    start_cleanup(helper);
    return;
  }
  if (error != NULL || helper->device == NULL) {
    fail(helper, "connect", "server_unavailable");
    if (error != NULL)
      g_error_free(error);
    start_cleanup(helper);
    return;
  }

  set_stage(helper, "attach");
  helper->operation_in_flight = TRUE;
  frida_device_attach(helper->device, helper->pid, NULL,
      helper->operation_cancel, on_session_attached, helper);
}

static gboolean
on_operation_timeout(gpointer user_data)
{
  Helper *helper = user_data;
  helper->timeout_source = 0;
  helper->timed_out = TRUE;
  if (helper->error_code == NULL)
    fail(helper, helper->stage,
        (g_strcmp0(helper->stage, "await_result") == 0 &&
            helper->response_error_code != NULL)
            ? helper->response_error_code : "timeout");
  g_cancellable_cancel(helper->operation_cancel);
  if (helper->operation_in_flight)
    helper->force_source = g_timeout_add(CANCEL_GRACE_MS, force_finish, helper);
  else
    start_cleanup(helper);
  return G_SOURCE_REMOVE;
}

static void
begin(Helper *helper, guint timeout_ms)
{
  helper->loop = g_main_loop_new(NULL, FALSE);
  helper->operation_cancel = g_cancellable_new();
  helper->cleanup_cancel = g_cancellable_new();
  helper->manager = frida_device_manager_new();
  helper->timeout_source = g_timeout_add(timeout_ms,
      on_operation_timeout, helper);
  set_stage(helper, "connect");
  helper->operation_in_flight = TRUE;
  frida_device_manager_add_remote_device(helper->manager,
      "127.0.0.1:27042", NULL, helper->operation_cancel,
      on_device_connected, helper);
  if (!helper->hard_timeout)
    g_main_loop_run(helper->loop);
}

static gboolean
read_limited_fd(int fd, guint8 **bytes, gsize *length, guint timeout_ms)
{
  guint8 *buffer = malloc(MAX_INPUT_BYTES + 1);
  if (buffer == NULL)
    return FALSE;

  struct timespec started;
  if (clock_gettime(CLOCK_MONOTONIC, &started) != 0) {
    free(buffer);
    return FALSE;
  }
  gsize used = 0;
  while (used <= MAX_INPUT_BYTES) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
      free(buffer);
      return FALSE;
    }
    int64_t elapsed_ms = (int64_t) (now.tv_sec - started.tv_sec) * 1000 +
        (now.tv_nsec - started.tv_nsec) / 1000000;
    int64_t remaining_ms = (int64_t) timeout_ms - elapsed_ms;
    if (remaining_ms <= 0) {
      free(buffer);
      return FALSE;
    }
    struct pollfd descriptor = { .fd = fd, .events = POLLIN };
    int ready = poll(&descriptor, 1, (int) remaining_ms);
    if (ready < 0 && errno == EINTR)
      continue;
    if (ready <= 0 || (descriptor.revents & (POLLERR | POLLNVAL)) != 0) {
      free(buffer);
      return FALSE;
    }
    ssize_t count = read(fd, buffer + used, MAX_INPUT_BYTES + 1 - used);
    if (count < 0 && errno == EINTR)
      continue;
    if (count < 0) {
      free(buffer);
      return FALSE;
    }
    if (count == 0)
      break;
    used += (gsize) count;
  }
  if (used > MAX_INPUT_BYTES) {
    free(buffer);
    return FALSE;
  }
  *bytes = buffer;
  *length = used;
  return TRUE;
}

static gboolean
read_script_file(const char *path, guint8 **bytes, gsize *length,
    guint timeout_ms)
{
  int fd = open(path, O_RDONLY | O_NONBLOCK);
  if (fd < 0)
    return FALSE;
  struct stat metadata;
  if (fstat(fd, &metadata) != 0 || !S_ISREG(metadata.st_mode) ||
      metadata.st_size < 0 ||
      metadata.st_size > MAX_INPUT_BYTES) {
    close(fd);
    return FALSE;
  }
  gboolean success = read_limited_fd(fd, bytes, length, timeout_ms);
  close(fd);
  return success;
}

static gboolean
parse_positive_integer(const char *text, guint64 max, guint64 *value)
{
  char *end = NULL;
  errno = 0;
  unsigned long long parsed = strtoull(text, &end, 10);
  if (errno != 0 || end == text || *end != '\0' || parsed == 0 || parsed > max)
    return FALSE;
  *value = (guint64) parsed;
  return TRUE;
}

static void
write_json(NSDictionary *object)
{
  NSError *error = nil;
  NSData *data = [NSJSONSerialization dataWithJSONObject:object options:0 error:&error];
  if (data == nil || data.length > MAX_INPUT_BYTES) {
    id dispatch = object[@"dispatch"];
    NSString *dispatch_value = [dispatch isKindOfClass:[NSString class]]
        ? dispatch : @"not_started";
    NSDictionary *fallback = @{@"ok": @NO, @"stage": @"output",
        @"code": (data == nil ? @"serialization_failed" : @"response_too_large"),
        @"dispatch": dispatch_value};
    NSData *fallback_data = [NSJSONSerialization dataWithJSONObject:fallback
        options:0 error:NULL];
    fwrite(fallback_data.bytes, 1, fallback_data.length, stdout);
    fputc('\n', stdout);
  } else {
    fwrite(data.bytes, 1, data.length, stdout);
    fputc('\n', stdout);
  }
  fflush(stdout);
}

static void
write_input_error(const gchar *code)
{
  write_json(@{@"ok": @NO, @"stage": @"input",
      @"code": [NSString stringWithUTF8String:code],
      @"dispatch": @"not_started"});
}

int
main(int argc, char **argv)
{
 @autoreleasepool {
  guint64 pid = 0;
  guint64 timeout_ms = DEFAULT_TIMEOUT_MS;
  const char *script_path = NULL;
  const char *binary_fd_value = NULL;
  const char *binary_max_value = NULL;
  gboolean use_stdin = FALSE;
  gboolean eternalize_requested = FALSE;

  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--pid") == 0 && i + 1 < argc) {
      if (!parse_positive_integer(argv[++i], UINT32_MAX, &pid)) {
        write_input_error("invalid_pid");
        return 2;
      }
    } else if (strcmp(argv[i], "--timeout-ms") == 0 && i + 1 < argc) {
      if (!parse_positive_integer(argv[++i], MAX_TIMEOUT_MS, &timeout_ms) ||
          timeout_ms < 1000) {
        write_input_error("invalid_timeout");
        return 2;
      }
    } else if (strcmp(argv[i], "--script") == 0 && i + 1 < argc) {
      script_path = argv[++i];
    } else if (strcmp(argv[i], "--binary-output-fd") == 0 && i + 1 < argc &&
        binary_fd_value == NULL) {
      binary_fd_value = argv[++i];
    } else if (strcmp(argv[i], "--max-binary-bytes") == 0 && i + 1 < argc &&
        binary_max_value == NULL) {
      binary_max_value = argv[++i];
    } else if (strcmp(argv[i], "--stdin") == 0) {
      use_stdin = TRUE;
    } else if (strcmp(argv[i], "--eternalize") == 0 && !eternalize_requested) {
      eternalize_requested = TRUE;
    } else {
      write_input_error("invalid_arguments");
      return 2;
    }
  }

  if (pid == 0 || (use_stdin == (script_path != NULL))) {
    write_input_error("invalid_arguments");
    return 2;
  }

  BinaryOutput binary_output = {0};
  BinaryOutputStatus binary_status = binary_output_parse(binary_fd_value,
      binary_max_value, &binary_output);
  if (binary_status != BINARY_OUTPUT_OK) {
    write_input_error(binary_output_status_name(binary_status));
    return 2;
  }
  if (binary_output.enabled) {
    binary_status = binary_output_validate(&binary_output);
    if (binary_status != BINARY_OUTPUT_OK) {
      write_input_error(binary_output_status_name(binary_status));
      return 2;
    }
  }

  guint8 *script_bytes = NULL;
  gsize script_length = 0;
  gboolean read_ok = use_stdin
      ? read_limited_fd(STDIN_FILENO, &script_bytes, &script_length,
          (guint) timeout_ms)
      : read_script_file(script_path, &script_bytes, &script_length,
          (guint) timeout_ms);
  if (!read_ok) {
    write_input_error("script_read_failed_or_too_large");
    return 2;
  }
  if (script_length == 0) {
    free(script_bytes);
    write_input_error("script_empty");
    return 2;
  }
  if (memchr(script_bytes, '\0', script_length) != NULL) {
    free(script_bytes);
    write_input_error("script_contains_nul");
    return 2;
  }

  NSString *script_source = [[NSString alloc] initWithBytes:script_bytes
      length:script_length encoding:NSUTF8StringEncoding];
  free(script_bytes);
  if (script_source == nil) {
    write_input_error("script_not_utf8");
    return 2;
  }

  Helper helper = {0};
  helper.pid = (guint) pid;
  helper.eternalize_requested = eternalize_requested;
  helper.binary_output = binary_output;
  helper.script_source = g_strdup([script_source UTF8String]);
  frida_init();
  begin(&helper, (guint) timeout_ms);

  NSMutableDictionary *output = [NSMutableDictionary dictionary];
  BOOL success = helper.error_code == NULL && helper.result_received &&
      helper.cleanup_code == NULL && !helper.hard_timeout &&
      (!helper.eternalize_requested || helper.script_eternalized) &&
      (!helper.binary_output.enabled || helper.binary_written);
  if (helper.binary_output.enabled && !success) {
    BinaryOutputStatus reset_status = binary_output_reset(&helper.binary_output);
    if (reset_status != BINARY_OUTPUT_OK && helper.error_code == NULL)
      fail(&helper, "binary_output", binary_output_status_name(reset_status));
    helper.binary_written = FALSE;
    helper.binary_byte_count = 0;
  }
  output[@"ok"] = @(success);
  output[@"stage"] = [NSString stringWithUTF8String:success ? "complete" :
      (helper.error_stage != NULL ? helper.error_stage : "cleanup")];
  output[@"dispatch"] = [NSString stringWithUTF8String:
      helper.result_received ? "confirmed" :
      (helper.load_started ? "unknown" : "not_started")];
  if (helper.script_eternalized)
    output[@"scriptLifetime"] = @"eternalized";
  if (helper.result_received && helper.result_json != NULL &&
      (!helper.binary_output.enabled || success)) {
    NSData *result_data = [[NSData alloc] initWithBytes:helper.result_json
        length:strlen(helper.result_json)];
    NSError *parse_error = nil;
    id result = [NSJSONSerialization JSONObjectWithData:result_data
        options:NSJSONReadingFragmentsAllowed error:&parse_error];
    output[@"result"] = result ?: [NSNull null];
  }
  if (!success) {
    output[@"code"] = [NSString stringWithUTF8String:
        helper.error_code ?: helper.cleanup_code ?: "helper_failed"];
  }
  if (helper.cleanup_code != NULL)
    output[@"cleanupCode"] = [NSString stringWithUTF8String:helper.cleanup_code];
  if (helper.hard_timeout)
    output[@"cleanupIncomplete"] = @YES;
  if (helper.binary_output.enabled) {
    output[@"binaryWritten"] = (success && helper.binary_written) ? @YES : @NO;
    if (success)
      output[@"binaryByteCount"] = @(helper.binary_byte_count);
  }
  write_json(output);

  if (!helper.hard_timeout) {
    g_clear_pointer(&helper.script_source, g_free);
    g_clear_pointer(&helper.result_json, g_free);
    g_clear_object(&helper.script);
    g_clear_object(&helper.session);
    g_clear_object(&helper.device);
    g_clear_object(&helper.manager);
    g_clear_object(&helper.operation_cancel);
    g_clear_object(&helper.cleanup_cancel);
    if (helper.loop != NULL)
      g_main_loop_unref(helper.loop);
  }
  return success ? 0 : 1;
 }
}
