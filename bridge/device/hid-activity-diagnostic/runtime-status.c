#include "runtime-status.h"

#include <stddef.h>

static int8_t mc_read_optional_bool(bool available,
                                    mc_runtime_bool_query query,
                                    void *context) {
    bool value = false;
    if (!available || query == NULL || !query(context, &value)) {
        return -1;
    }
    return value ? 1 : 0;
}

static void mc_write_optional_bool(FILE *stream, int8_t value) {
    if (value < 0) {
        fputs("null", stream);
    } else {
        fputs(value ? "true" : "false", stream);
    }
}

void mc_runtime_status_read(mc_runtime_status *status,
                            bool hid_query_available,
                            mc_runtime_bool_query hid_query,
                            void *hid_context,
                            bool code_signature_query_available,
                            mc_runtime_bool_query code_signature_query,
                            void *code_signature_context) {
    if (status == NULL) {
        return;
    }
    status->hid_entitlement_query_available =
        hid_query_available && hid_query != NULL;
    status->hid_event_monitor_entitlement = mc_read_optional_bool(
        status->hid_entitlement_query_available, hid_query, hid_context);
    status->code_signature_entitlements_validated = mc_read_optional_bool(
        code_signature_query_available, code_signature_query,
        code_signature_context);
}

void mc_runtime_status_write_json(FILE *stream,
                                  const mc_runtime_status *status) {
    if (stream == NULL || status == NULL) {
        return;
    }
    fprintf(stream,
            "\"hidEventMonitorEntitlementAvailable\":%s,"
            "\"hidEventMonitorEntitlement\":",
            status->hid_entitlement_query_available ? "true" : "false");
    mc_write_optional_bool(stream, status->hid_event_monitor_entitlement);
    fputs(",\"codeSignatureEntitlementsValidated\":", stream);
    mc_write_optional_bool(stream,
                           status->code_signature_entitlements_validated);
}
