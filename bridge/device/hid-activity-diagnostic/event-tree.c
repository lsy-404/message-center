#include "event-tree.h"

#include <stddef.h>

typedef struct {
    uint64_t types[MC_HID_EVENT_TYPE_LIMIT];
    uint64_t unknown_types;
    size_t visited;
} mc_hid_tree_result;

static bool mc_visit(mc_hid_tree_result *result,
                     const mc_hid_event_access *access,
                     const void *event,
                     size_t depth) {
    const void *array = access->children(access->context, event);
    long count;
    if (array == NULL) {
        return true;
    }
    if (!access->is_array(access->context, array)) {
        return false;
    }
    count = access->array_count(access->context, array);
    if (count < 0 || count > MC_HID_MAX_CHILDREN_PER_EVENT ||
        (count > 0 && depth >= MC_HID_MAX_TREE_DEPTH) ||
        result->visited + (size_t)count > MC_HID_MAX_TREE_NODES) {
        return false;
    }
    for (long index = 0; index < count; ++index) {
        const void *child = access->array_value(access->context, array, index);
        uint32_t type;
        if (child == NULL) {
            return false;
        }
        ++result->visited;
        type = access->event_type(access->context, child);
        if (type < MC_HID_EVENT_TYPE_LIMIT) {
            ++result->types[type];
        } else {
            ++result->unknown_types;
        }
        if (!mc_visit(result, access, child, depth + 1)) {
            return false;
        }
    }
    return true;
}

bool mc_hid_event_tree_add(mc_hid_event_counters *counters,
                           const mc_hid_event_access *access,
                           const void *root_event) {
    mc_hid_tree_result result = { .visited = 1 };
    uint32_t type;
    if (counters == NULL || access == NULL || root_event == NULL ||
        access->event_type == NULL || access->children == NULL ||
        access->is_array == NULL || access->array_count == NULL ||
        access->array_value == NULL) {
        return false;
    }
    ++counters->events;
    type = access->event_type(access->context, root_event);
    if (type < MC_HID_EVENT_TYPE_LIMIT) {
        ++counters->root_types[type];
    } else {
        ++counters->unknown_root_types;
    }
    if (!mc_visit(&result, access, root_event, 0)) {
        ++counters->malformed_trees;
        return false;
    }
    for (size_t index = 0; index < MC_HID_EVENT_TYPE_LIMIT; ++index) {
        counters->child_types[index] += result.types[index];
    }
    counters->unknown_child_types += result.unknown_types;
    return true;
}
