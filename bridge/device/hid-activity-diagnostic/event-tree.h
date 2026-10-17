#ifndef MESSAGE_CENTER_HID_EVENT_TREE_H
#define MESSAGE_CENTER_HID_EVENT_TREE_H

#include <stdbool.h>
#include <stdint.h>

#define MC_HID_EVENT_TYPE_LIMIT 64
#define MC_HID_MAX_CHILDREN_PER_EVENT 32
#define MC_HID_MAX_TREE_DEPTH 4
#define MC_HID_MAX_TREE_NODES 64

typedef struct {
    uint64_t root_types[MC_HID_EVENT_TYPE_LIMIT];
    uint64_t child_types[MC_HID_EVENT_TYPE_LIMIT];
    uint64_t unknown_root_types;
    uint64_t unknown_child_types;
    uint64_t malformed_trees;
    uint64_t events;
} mc_hid_event_counters;

typedef struct {
    void *context;
    uint32_t (*event_type)(void *context, const void *event);
    const void *(*children)(void *context, const void *event);
    bool (*is_array)(void *context, const void *array);
    long (*array_count)(void *context, const void *array);
    const void *(*array_value)(void *context, const void *array, long index);
} mc_hid_event_access;

bool mc_hid_event_tree_add(mc_hid_event_counters *counters,
                           const mc_hid_event_access *access,
                           const void *root_event);

#endif
