#ifndef MESSAGE_CENTER_BINARY_OUTPUT_H
#define MESSAGE_CENTER_BINARY_OUTPUT_H

#include <stddef.h>
#include <stdint.h>

#define BINARY_OUTPUT_MAX_BYTES (50u * 1024u * 1024u)

typedef struct {
  int enabled;
  int fd;
  uint64_t max_bytes;
} BinaryOutput;

typedef enum {
  BINARY_OUTPUT_OK = 0,
  BINARY_OUTPUT_INVALID_FLAGS,
  BINARY_OUTPUT_INVALID_FD,
  BINARY_OUTPUT_INVALID_LIMIT,
  BINARY_OUTPUT_FD_NOT_REGULAR,
  BINARY_OUTPUT_FD_NOT_EMPTY,
  BINARY_OUTPUT_FD_NOT_WRITABLE,
  BINARY_OUTPUT_FD_BAD_OFFSET,
  BINARY_OUTPUT_RESET_FAILED,
  BINARY_OUTPUT_WRITE_FAILED,
  BINARY_OUTPUT_TOO_LARGE
} BinaryOutputStatus;

BinaryOutputStatus binary_output_parse(const char *fd_value,
    const char *max_bytes_value, BinaryOutput *output);
BinaryOutputStatus binary_output_validate(BinaryOutput *output);
BinaryOutputStatus binary_output_write(BinaryOutput *output,
    const void *bytes, size_t length);
BinaryOutputStatus binary_output_reset(const BinaryOutput *output);
const char *binary_output_status_name(BinaryOutputStatus status);

#endif
