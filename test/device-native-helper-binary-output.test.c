#define _POSIX_C_SOURCE 200809L

#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../bridge/device/native-frida-helper/binary-output.h"

static BinaryOutput
parse_output(int fd, uint64_t maximum)
{
  char fd_text[32];
  char max_text[32];
  snprintf(fd_text, sizeof(fd_text), "%d", fd);
  snprintf(max_text, sizeof(max_text), "%llu", (unsigned long long) maximum);
  BinaryOutput output;
  assert(binary_output_parse(fd_text, max_text, &output) == BINARY_OUTPUT_OK);
  return output;
}

int
main(void)
{
  BinaryOutput output;
  assert(binary_output_parse(NULL, NULL, &output) == BINARY_OUTPUT_OK);
  assert(!output.enabled && output.fd == -1);
  assert(binary_output_parse("3", NULL, &output) == BINARY_OUTPUT_INVALID_FLAGS);
  assert(binary_output_parse(NULL, "32", &output) == BINARY_OUTPUT_INVALID_FLAGS);
  assert(binary_output_parse("x", "32", &output) == BINARY_OUTPUT_INVALID_FD);
  assert(binary_output_parse("2", "32", &output) == BINARY_OUTPUT_INVALID_FD);
  assert(binary_output_parse("2147483648", "32", &output) == BINARY_OUTPUT_INVALID_FD);
  assert(binary_output_parse("3", "0", &output) == BINARY_OUTPUT_INVALID_LIMIT);
  assert(binary_output_parse("3", "52428801", &output) == BINARY_OUTPUT_INVALID_LIMIT);
  assert(binary_output_parse("3", "52428800", &output) == BINARY_OUTPUT_OK);
  assert(output.enabled && output.max_bytes == BINARY_OUTPUT_MAX_BYTES);

  char path[] = "/tmp/message-center-binary-output-XXXXXX";
  int fd = mkstemp(path);
  assert(fd >= 3);
  output = parse_output(fd, 8);
  assert(binary_output_validate(&output) == BINARY_OUTPUT_OK);

  const unsigned char sample[] = { 0x00, 0x01, 0x7f, 0x80, 0xff };
  assert(binary_output_write(&output, sample, sizeof(sample)) == BINARY_OUTPUT_OK);
  assert(lseek(fd, 0, SEEK_CUR) == (off_t) sizeof(sample));
  unsigned char actual[sizeof(sample)] = {0};
  assert(pread(fd, actual, sizeof(actual), 0) == (ssize_t) sizeof(actual));
  assert(memcmp(actual, sample, sizeof(sample)) == 0);
  assert(binary_output_write(&output, sample, 9) == BINARY_OUTPUT_TOO_LARGE);
  assert(binary_output_reset(&output) == BINARY_OUTPUT_OK);
  struct stat metadata;
  assert(fstat(fd, &metadata) == 0 && metadata.st_size == 0);
  close(fd);
  unlink(path);

  char offset_path[] = "/tmp/message-center-binary-output-offset-XXXXXX";
  fd = mkstemp(offset_path);
  assert(fd >= 3);
  assert(lseek(fd, 1, SEEK_SET) == 1);
  output = parse_output(fd, 8);
  assert(binary_output_validate(&output) == BINARY_OUTPUT_FD_BAD_OFFSET);
  close(fd);
  unlink(offset_path);

  char append_path[] = "/tmp/message-center-binary-output-append-XXXXXX";
  fd = mkstemp(append_path);
  assert(fd >= 3);
  close(fd);
  fd = open(append_path, O_WRONLY | O_APPEND);
  assert(fd >= 3);
  output = parse_output(fd, 8);
  assert(binary_output_validate(&output) == BINARY_OUTPUT_FD_NOT_WRITABLE);
  close(fd);
  unlink(append_path);

  char nonempty_path[] = "/tmp/message-center-binary-output-nonempty-XXXXXX";
  fd = mkstemp(nonempty_path);
  assert(fd >= 3);
  assert(write(fd, sample, sizeof(sample)) == (ssize_t) sizeof(sample));
  output = parse_output(fd, 8);
  assert(binary_output_validate(&output) == BINARY_OUTPUT_FD_NOT_EMPTY);
  close(fd);
  unlink(nonempty_path);

  char readonly_path[] = "/tmp/message-center-binary-output-readonly-XXXXXX";
  int writable_fd = mkstemp(readonly_path);
  assert(writable_fd >= 3);
  close(writable_fd);
  fd = open(readonly_path, O_RDONLY);
  assert(fd >= 3);
  output = parse_output(fd, 8);
  assert(binary_output_validate(&output) == BINARY_OUTPUT_FD_NOT_WRITABLE);
  close(fd);
  unlink(readonly_path);

  fd = open("/dev/null", O_WRONLY);
  assert(fd >= 3);
  output = parse_output(fd, 8);
  assert(binary_output_validate(&output) == BINARY_OUTPUT_FD_NOT_REGULAR);
  close(fd);

  puts("native helper binary output tests passed");
  return 0;
}
