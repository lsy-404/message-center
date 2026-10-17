#include "../bridge/device/hid-activity-diagnostic/event-tree.h"

#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct fake_event fake_event;
typedef struct {
    const fake_event *items[MC_HID_MAX_CHILDREN_PER_EVENT + 1];
    long count;
    bool valid_array;
} fake_array;
struct fake_event {
    uint32_t type;
    const fake_array *children;
};

static uint32_t fake_type(void *context, const void *event) {
    (void)context;
    return ((const fake_event *)event)->type;
}

static const void *fake_children(void *context, const void *event) {
    (void)context;
    return ((const fake_event *)event)->children;
}

static bool fake_is_array(void *context, const void *array) {
    (void)context;
    return ((const fake_array *)array)->valid_array;
}

static long fake_array_count(void *context, const void *array) {
    (void)context;
    return ((const fake_array *)array)->count;
}

static const void *fake_array_value(void *context, const void *array, long index) {
    (void)context;
    return ((const fake_array *)array)->items[index];
}

static mc_hid_event_access make_access(void) {
    mc_hid_event_access access = {
        .event_type = fake_type,
        .children = fake_children,
        .is_array = fake_is_array,
        .array_count = fake_array_count,
        .array_value = fake_array_value,
    };
    return access;
}

static void test_counts_root_and_nested_child_types(void) {
    mc_hid_event_counters counters = {0};
    mc_hid_event_access access = make_access();
    fake_event leaf = { .type = 11 };
    fake_array nested = { .items = { &leaf }, .count = 1, .valid_array = true };
    fake_event child = { .type = 12, .children = &nested };
    fake_array root_children = { .items = { &child }, .count = 1, .valid_array = true };
    fake_event root = { .type = 7, .children = &root_children };

    assert(mc_hid_event_tree_add(&counters, &access, &root));
    assert(counters.events == 1);
    assert(counters.root_types[7] == 1);
    assert(counters.child_types[12] == 1);
    assert(counters.child_types[11] == 1);
    assert(counters.malformed_trees == 0);
}

static void test_rejects_non_array_and_null_child_without_partial_counts(void) {
    mc_hid_event_counters counters = {0};
    mc_hid_event_access access = make_access();
    fake_event child = { .type = 11 };
    fake_array invalid = { .items = { &child }, .count = 1, .valid_array = false };
    fake_event root = { .type = 7, .children = &invalid };

    assert(!mc_hid_event_tree_add(&counters, &access, &root));
    assert(counters.root_types[7] == 1);
    assert(counters.child_types[11] == 0);
    assert(counters.malformed_trees == 1);

    invalid.valid_array = true;
    invalid.items[0] = NULL;
    assert(!mc_hid_event_tree_add(&counters, &access, &root));
    assert(counters.child_types[11] == 0);
    assert(counters.malformed_trees == 2);
}

static void test_enforces_child_depth_and_node_limits(void) {
    mc_hid_event_counters counters = {0};
    mc_hid_event_access access = make_access();
    fake_array arrays[MC_HID_MAX_TREE_DEPTH + 2] = {0};
    fake_event events[MC_HID_MAX_TREE_DEPTH + 2] = {0};
    for (size_t index = 0; index < MC_HID_MAX_TREE_DEPTH + 1; ++index) {
        events[index].type = (uint32_t)(index + 1);
        arrays[index].items[0] = &events[index + 1];
        arrays[index].count = 1;
        arrays[index].valid_array = true;
        events[index].children = &arrays[index];
    }
    events[MC_HID_MAX_TREE_DEPTH + 1].type = 12;
    assert(!mc_hid_event_tree_add(&counters, &access, &events[0]));
    assert(counters.malformed_trees == 1);
    for (size_t index = 0; index < MC_HID_EVENT_TYPE_LIMIT; ++index) {
        assert(counters.child_types[index] == 0);
    }

    memset(&counters, 0, sizeof(counters));
    fake_event fanout_root = { .type = 7 };
    fake_array fanout[MC_HID_MAX_CHILDREN_PER_EVENT + 1] = {0};
    fake_event fanout_children[MC_HID_MAX_CHILDREN_PER_EVENT] = {0};
    fake_event leaf = { .type = 12 };
    fake_array leaf_array = { .items = { &leaf }, .count = 1, .valid_array = true };
    for (size_t index = 0; index < MC_HID_MAX_CHILDREN_PER_EVENT; ++index) {
        fanout_children[index].type = 3;
        fanout_children[index].children = &leaf_array;
        fanout[0].items[index] = &fanout_children[index];
    }
    fanout[0].count = MC_HID_MAX_CHILDREN_PER_EVENT;
    fanout[0].valid_array = true;
    fanout_root.children = &fanout[0];
    assert(!mc_hid_event_tree_add(&counters, &access, &fanout_root));
    assert(counters.malformed_trees == 1);
    assert(counters.child_types[3] == 0);
    assert(counters.child_types[12] == 0);
}

static void test_counts_unknown_event_type_without_payload_access(void) {
    mc_hid_event_counters counters = {0};
    mc_hid_event_access access = make_access();
    fake_event child = { .type = UINT32_MAX };
    fake_array children = { .items = { &child }, .count = 1, .valid_array = true };
    fake_event root = { .type = UINT32_MAX, .children = &children };

    assert(mc_hid_event_tree_add(&counters, &access, &root));
    assert(counters.unknown_root_types == 1);
    assert(counters.unknown_child_types == 1);
}

static void test_rejects_negative_and_excessive_array_counts(void) {
    mc_hid_event_counters counters = {0};
    mc_hid_event_access access = make_access();
    fake_array children = { .count = -1, .valid_array = true };
    fake_event root = { .type = 7, .children = &children };

    assert(!mc_hid_event_tree_add(&counters, &access, &root));
    assert(counters.malformed_trees == 1);
    children.count = MC_HID_MAX_CHILDREN_PER_EVENT + 1;
    assert(!mc_hid_event_tree_add(&counters, &access, &root));
    assert(counters.malformed_trees == 2);
}

int main(void) {
    test_counts_root_and_nested_child_types();
    test_rejects_non_array_and_null_child_without_partial_counts();
    test_enforces_child_depth_and_node_limits();
    test_counts_unknown_event_type_without_payload_access();
    test_rejects_negative_and_excessive_array_counts();
    return 0;
}
