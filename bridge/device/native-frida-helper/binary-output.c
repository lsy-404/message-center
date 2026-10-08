#define _POSIX_C_SOURCE 200809L

#include "binary-output.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static int
parse_decimal(const char *text, uint64_t maximum, uint64_t *value)
{
  if (text == NULL || text[0] == '\0')
    return 0;
  for (const unsigned char *cursor = (const unsigned char *) text;
      *cursor != '\0'; cursor++) {
    if (*cursor < '0' || *cursor > '9')
      return 0;
  }
  errno = 0;
  char *end = NULL;
  unsigned long long parsed = strtoull(text, &end, 10);
  if (errno != 0 || end == text || *end != '\0' || parsed == 0 ||
      parsed > maximum)
    return 0;
  *value = (uint64_t) parsed;
  return 1;
}

BinaryOutputStatus
binary_output_parse(const char *fd_value, const char *max_bytes_value,
    BinaryOutput *output)
{
  if (output == NULL)
    return BINARY_OUTPUT_INVALID_FLAGS;
  memset(output, 0, sizeof(*output));
  output->fd = -1;
  if (fd_value == NULL && max_bytes_value == NULL)
    return BINARY_OUTPUT_OK;
  if (fd_value == NULL || max_bytes_value == NULL)
    return BINARY_OUTPUT_INVALID_FLAGS;

  uint64_t fd = 0;
  if (!parse_decimal(fd_value, INT_MAX, &fd) || fd <= STDERR_FILENO)
    return BINARY_OUTPUT_INVALID_FD;
  uint64_t max_bytes = 0;
  if (!parse_decimal(max_bytes_value, BINARY_OUTPUT_MAX_BYTES, &max_bytes))
    return BINARY_OUTPUT_INVALID_LIMIT;

  output->enabled = 1;
  output->fd = (int) fd;
  output->max_bytes = max_bytes;
  return BINARY_OUTPUT_OK;
}

BinaryOutputStatus
binary_output_validate(BinaryOutput *output)
{
  if (output == NULL || !output->enabled || output->fd <= STDERR_FILENO ||
      output->max_bytes == 0 || output->max_bytes > BINARY_OUTPUT_MAX_BYTES)
    return BINARY_OUTPUT_INVALID_FLAGS;

  struct stat metadata;
  if (fstat(output->fd, &metadata) != 0)
    return BINARY_OUTPUT_INVALID_FD;
  if (!S_ISREG(metadata.st_mode))
    return BINARY_OUTPUT_FD_NOT_REGULAR;
  if (metadata.st_size != 0)
    return BINARY_OUTPUT_FD_NOT_EMPTY;

  int flags = fcntl(output->fd, F_GETFL);
  if (flags < 0 || (flags & O_ACCMODE) == O_RDONLY || (flags & O_APPEND) != 0)
    return BINARY_OUTPUT_FD_NOT_WRITABLE;
  if (lseek(output->fd, 0, SEEK_CUR) != 0)
    return BINARY_OUTPUT_FD_BAD_OFFSET;
  if (ftruncate(output->fd, 0) != 0 || lseek(output->fd, 0, SEEK_SET) != 0)
    return BINARY_OUTPUT_RESET_FAILED;
  return BINARY_OUTPUT_OK;
}

BinaryOutputStatus
binary_output_reset(const BinaryOutput *output)
{
  if (output == NULL || !output->enabled || output->fd <= STDERR_FILENO)
    return BINARY_OUTPUT_INVALID_FLAGS;
  if (ftruncate(output->fd, 0) != 0 || lseek(output->fd, 0, SEEK_SET) != 0)
    return BINARY_OUTPUT_RESET_FAILED;
  return BINARY_OUTPUT_OK;
}

BinaryOutputStatus
binary_output_write(BinaryOutput *output, const void *bytes, size_t length)
{
  if (output == NULL || !output->enabled)
    return BINARY_OUTPUT_INVALID_FLAGS;
  if (bytes == NULL || length == 0)
    return BINARY_OUTPUT_WRITE_FAILED;
  if (length > output->max_bytes)
    return BINARY_OUTPUT_TOO_LARGE;

  size_t written = 0;
  while (written < length) {
    ssize_t count = write(output->fd, (const unsigned char *) bytes + written,
        length - written);
    if (count < 0 && errno == EINTR)
      continue;
    if (count <= 0) {
      BinaryOutputStatus reset = binary_output_reset(output);
      return reset == BINARY_OUTPUT_OK ? BINARY_OUTPUT_WRITE_FAILED : reset;
    }
    written += (size_t) count;
  }
  return BINARY_OUTPUT_OK;
}

const char *
binary_output_status_name(BinaryOutputStatus status)
{
  switch (status) {
    case BINARY_OUTPUT_OK: return "ok";
    case BINARY_OUTPUT_INVALID_FLAGS: return "invalid_binary_output_flags";
    case BINARY_OUTPUT_INVALID_FD: return "invalid_binary_output_fd";
    case BINARY_OUTPUT_INVALID_LIMIT: return "invalid_binary_output_limit";
    case BINARY_OUTPUT_FD_NOT_REGULAR: return "binary_output_not_regular";
    case BINARY_OUTPUT_FD_NOT_EMPTY: return "binary_output_not_empty";
    case BINARY_OUTPUT_FD_NOT_WRITABLE: return "binary_output_not_writable";
    case BINARY_OUTPUT_FD_BAD_OFFSET: return "binary_output_bad_offset";
    case BINARY_OUTPUT_RESET_FAILED: return "binary_output_reset_failed";
    case BINARY_OUTPUT_WRITE_FAILED: return "binary_output_write_failed";
    case BINARY_OUTPUT_TOO_LARGE: return "binary_output_too_large";
  }
  return "binary_output_invalid";
}
