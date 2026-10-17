#ifndef MC_HID_RUNTIME_STATUS_H
#define MC_HID_RUNTIME_STATUS_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

typedef bool (*mc_runtime_bool_query)(void *context, bool *value);

typedef struct {
    bool hid_entitlement_query_available;
    int8_t hid_event_monitor_entitlement;
    int8_t code_signature_entitlements_validated;
} mc_runtime_status;

void mc_runtime_status_read(mc_runtime_status *status,
                            bool hid_query_available,
                            mc_runtime_bool_query hid_query,
                            void *hid_context,
                            bool code_signature_query_available,
                            mc_runtime_bool_query code_signature_query,
                            void *code_signature_context);
void mc_runtime_status_write_json(FILE *stream,
                                  const mc_runtime_status *status);

#endif
