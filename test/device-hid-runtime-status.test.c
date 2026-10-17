#include "../bridge/device/hid-activity-diagnostic/runtime-status.h"

#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    bool succeeds;
    bool value;
} fake_query;

static bool read_fake_query(void *context, bool *value) {
    const fake_query *query = context;
    if (!query->succeeds) {
        return false;
    }
    *value = query->value;
    return true;
}

static void read_json(const mc_runtime_status *status, char *buffer,
                      size_t buffer_size) {
    FILE *stream = tmpfile();
    assert(stream != NULL);
    mc_runtime_status_write_json(stream, status);
    assert(fflush(stream) == 0);
    rewind(stream);
    size_t length = fread(buffer, 1, buffer_size - 1, stream);
    buffer[length] = '\0';
    fclose(stream);
}

static void test_available_true_and_false_results(void) {
    fake_query hid = { .succeeds = true, .value = true };
    fake_query signature = { .succeeds = true, .value = false };
    mc_runtime_status status = {0};
    char json[256];

    mc_runtime_status_read(&status, true, read_fake_query, &hid, true,
                           read_fake_query, &signature);
    read_json(&status, json, sizeof(json));
    assert(status.hid_entitlement_query_available);
    assert(status.hid_event_monitor_entitlement == 1);
    assert(status.code_signature_entitlements_validated == 0);
    assert(strstr(json, "\"hidEventMonitorEntitlementAvailable\":true") != NULL);
    assert(strstr(json, "\"hidEventMonitorEntitlement\":true") != NULL);
    assert(strstr(json, "\"codeSignatureEntitlementsValidated\":false") != NULL);

    hid.value = false;
    signature.value = true;
    mc_runtime_status_read(&status, true, read_fake_query, &hid, true,
                           read_fake_query, &signature);
    read_json(&status, json, sizeof(json));
    assert(status.hid_event_monitor_entitlement == 0);
    assert(status.code_signature_entitlements_validated == 1);
    assert(strstr(json, "\"hidEventMonitorEntitlement\":false") != NULL);
    assert(strstr(json, "\"codeSignatureEntitlementsValidated\":true") != NULL);
}

static void test_missing_apis_and_query_errors_are_unknown(void) {
    fake_query failing = { .succeeds = false, .value = true };
    mc_runtime_status status = {0};
    char json[256];

    mc_runtime_status_read(&status, false, NULL, NULL, false, NULL, NULL);
    read_json(&status, json, sizeof(json));
    assert(!status.hid_entitlement_query_available);
    assert(status.hid_event_monitor_entitlement == -1);
    assert(status.code_signature_entitlements_validated == -1);
    assert(strstr(json, "\"hidEventMonitorEntitlementAvailable\":false") != NULL);
    assert(strstr(json, "\"hidEventMonitorEntitlement\":null") != NULL);
    assert(strstr(json, "\"codeSignatureEntitlementsValidated\":null") != NULL);

    mc_runtime_status_read(&status, true, read_fake_query, &failing, true,
                           read_fake_query, &failing);
    read_json(&status, json, sizeof(json));
    assert(status.hid_entitlement_query_available);
    assert(status.hid_event_monitor_entitlement == -1);
    assert(status.code_signature_entitlements_validated == -1);
    assert(strstr(json, "\"hidEventMonitorEntitlementAvailable\":true") != NULL);
    assert(strstr(json, "\"hidEventMonitorEntitlement\":null") != NULL);
    assert(strstr(json, "\"codeSignatureEntitlementsValidated\":null") != NULL);
}

int main(void) {
    test_available_true_and_false_results();
    test_missing_apis_and_query_errors_are_unknown();
    return 0;
}
