#define _DARWIN_C_SOURCE

#include "event-tree.h"

#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <math.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MC_MAX_SECONDS 300
#define MC_MAX_EVENTS 25000

typedef void (*mc_hid_callback)(void *, void *, void *, void *);
typedef void *(*mc_create_fn)(void *, int, void *);
typedef void (*mc_register_fn)(void *, mc_hid_callback, void *, void *);
typedef void (*mc_client_fn)(void *);
typedef void (*mc_runloop_fn)(void *, CFRunLoopRef, CFStringRef);
typedef uint32_t (*mc_event_type_fn)(void *);
typedef CFArrayRef (*mc_event_children_fn)(void *);

typedef struct {
    mc_hid_event_counters counters;
    mc_hid_event_access access;
    mc_event_type_fn event_type;
    mc_event_children_fn event_children;
    CFRunLoopRef run_loop;
    bool stopped_by_limit;
} mc_monitor;

static volatile sig_atomic_t mc_stop_requested = 0;

static void mc_signal_handler(int signal_number) {
    (void)signal_number;
    mc_stop_requested = 1;
}

static double mc_monotonic_seconds(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        return -1.0;
    }
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

static uint32_t mc_get_event_type(void *context, const void *event) {
    mc_monitor *monitor = context;
    return monitor->event_type((void *)event);
}

static const void *mc_get_children(void *context, const void *event) {
    mc_monitor *monitor = context;
    return monitor->event_children((void *)event);
}

static bool mc_is_cf_array(void *context, const void *array) {
    (void)context;
    return CFGetTypeID((CFTypeRef)array) == CFArrayGetTypeID();
}

static long mc_array_count(void *context, const void *array) {
    (void)context;
    return (long)CFArrayGetCount((CFArrayRef)array);
}

static const void *mc_array_value(void *context, const void *array, long index) {
    (void)context;
    return CFArrayGetValueAtIndex((CFArrayRef)array, (CFIndex)index);
}

static void mc_record_event(void *target, void *refcon, void *queue, void *event) {
    mc_monitor *monitor = target;
    (void)refcon;
    (void)queue;
    if (monitor == NULL || event == NULL ||
        monitor->counters.events >= MC_MAX_EVENTS) {
        if (monitor != NULL) {
            monitor->stopped_by_limit = true;
            CFRunLoopStop(monitor->run_loop);
        }
        return;
    }
    (void)mc_hid_event_tree_add(&monitor->counters, &monitor->access, event);
    if (monitor->counters.events >= MC_MAX_EVENTS) {
        monitor->stopped_by_limit = true;
        CFRunLoopStop(monitor->run_loop);
    }
}

static void mc_print_type_counts(const uint64_t *counts) {
    bool first = true;
    putchar('{');
    for (unsigned index = 0; index < MC_HID_EVENT_TYPE_LIMIT; ++index) {
        if (counts[index] == 0) {
            continue;
        }
        printf("%s\"%u\":%" PRIu64, first ? "" : ",", index, counts[index]);
        first = false;
    }
    putchar('}');
}

static void mc_print_status(const mc_monitor *monitor, bool ready, bool running,
                            double elapsed, time_t started_at, time_t ended_at,
                            const char *stop_reason, unsigned teardown_errors) {
    printf("{\"ready\":%s,\"running\":%s,\"startedAt\":%lld,\"endedAt\":",
           ready ? "true" : "false", running ? "true" : "false",
           (long long)started_at);
    if (ended_at == 0) {
        fputs("null", stdout);
    } else {
        printf("%lld", (long long)ended_at);
    }
    printf(",\"elapsedSeconds\":%.3f,\"events\":%" PRIu64 ",\"rootTypes\":",
           elapsed, monitor->counters.events);
    mc_print_type_counts(monitor->counters.root_types);
    fputs(",\"childTypes\":", stdout);
    mc_print_type_counts(monitor->counters.child_types);
    printf(",\"unknownRootTypes\":%" PRIu64 ",\"unknownChildTypes\":%" PRIu64
           ",\"malformedTrees\":%" PRIu64 ",\"teardownErrors\":%u,\"stopReason\":\"%s\"}\n",
           monitor->counters.unknown_root_types,
           monitor->counters.unknown_child_types,
           monitor->counters.malformed_trees, teardown_errors, stop_reason);
    fflush(stdout);
}

static int mc_parse_duration(int argc, char **argv, unsigned *seconds) {
    char *end = NULL;
    unsigned long parsed;
    if (argc == 1) {
        *seconds = MC_MAX_SECONDS;
        return 0;
    }
    if (argc != 3 || strcmp(argv[1], "--seconds") != 0 || argv[2][0] == '\0') {
        return -1;
    }
    errno = 0;
    parsed = strtoul(argv[2], &end, 10);
    if (errno != 0 || end == argv[2] || *end != '\0' || parsed < 1 ||
        parsed > MC_MAX_SECONDS || parsed > UINT_MAX) {
        return -1;
    }
    *seconds = (unsigned)parsed;
    return 0;
}

int main(int argc, char **argv) {
    const char *framework_path = "/System/Library/Frameworks/IOKit.framework/IOKit";
    unsigned seconds = MC_MAX_SECONDS;
    void *io = NULL;
    void *client = NULL;
    CFRunLoopRef run_loop = NULL;
    CFStringRef mode = kCFRunLoopDefaultMode;
    mc_create_fn create_client = NULL;
    mc_register_fn register_callback = NULL;
    mc_client_fn unregister_callback = NULL;
    mc_runloop_fn schedule_client = NULL;
    mc_runloop_fn unschedule_client = NULL;
    mc_monitor monitor = {0};
    bool registered = false;
    bool scheduled = false;
    bool ready = false;
    unsigned teardown_errors = 0;
    double started_monotonic;
    double deadline;
    time_t started_wall = 0;
    const char *stop_reason = "duration";
    int exit_code = 1;

    if (mc_parse_duration(argc, argv, &seconds) != 0) {
        fputs("usage: hid-activity-diagnostic [--seconds 1..300]\n", stderr);
        return 2;
    }
    signal(SIGTERM, mc_signal_handler);
    signal(SIGINT, mc_signal_handler);
    io = dlopen(framework_path, RTLD_NOW | RTLD_LOCAL);
    if (io == NULL) {
        fputs("hid_activity_error: iokit_unavailable\n", stderr);
        goto cleanup;
    }
#define MC_BIND(name, symbol) do { \
    void *symbol_address = dlsym(io, symbol); \
    _Static_assert(sizeof(name) == sizeof(symbol_address), "function pointer ABI size"); \
    if (symbol_address == NULL) { \
        fputs("hid_activity_error: required_export_unavailable\n", stderr); \
        goto cleanup; \
    } \
    memcpy(&(name), &symbol_address, sizeof(name)); \
} while (0)
    MC_BIND(create_client, "IOHIDEventSystemClientCreateWithType");
    MC_BIND(register_callback, "IOHIDEventSystemClientRegisterEventCallback");
    MC_BIND(unregister_callback, "IOHIDEventSystemClientUnregisterEventCallback");
    MC_BIND(schedule_client, "IOHIDEventSystemClientScheduleWithRunLoop");
    MC_BIND(unschedule_client, "IOHIDEventSystemClientUnscheduleWithRunLoop");
    MC_BIND(monitor.event_type, "IOHIDEventGetType");
    MC_BIND(monitor.event_children, "IOHIDEventGetChildren");
#undef MC_BIND

    client = create_client(kCFAllocatorDefault, 1, NULL);
    if (client == NULL || mode == NULL) {
        fputs("hid_activity_error: client_creation_failed\n", stderr);
        goto cleanup;
    }
    run_loop = CFRunLoopGetCurrent();
    if (run_loop == NULL) {
        fputs("hid_activity_error: run_loop_unavailable\n", stderr);
        goto cleanup;
    }
    monitor.run_loop = run_loop;
    monitor.access.context = &monitor;
    monitor.access.event_type = mc_get_event_type;
    monitor.access.children = mc_get_children;
    monitor.access.is_array = mc_is_cf_array;
    monitor.access.array_count = mc_array_count;
    monitor.access.array_value = mc_array_value;
    register_callback(client, mc_record_event, &monitor, NULL);
    registered = true;
    schedule_client(client, run_loop, mode);
    scheduled = true;

    started_monotonic = mc_monotonic_seconds();
    if (started_monotonic < 0.0) {
        fputs("hid_activity_error: monotonic_clock_unavailable\n", stderr);
        goto cleanup;
    }
    deadline = started_monotonic + (double)seconds;
    started_wall = time(NULL);
    ready = true;
    mc_print_status(&monitor, true, true, 0.0, started_wall, 0, "running", 0);

    while (!mc_stop_requested && !monitor.stopped_by_limit) {
        double now = mc_monotonic_seconds();
        if (now < 0.0 || now >= deadline) {
            stop_reason = now < 0.0 ? "clock_error" : "duration";
            break;
        }
        SInt32 run_result = CFRunLoopRunInMode(mode, fmin(1.0, deadline - now), false);
        if (mc_stop_requested) {
            stop_reason = "signal";
            break;
        }
        if (monitor.stopped_by_limit) {
            stop_reason = "event_limit";
            break;
        }
        if (run_result == kCFRunLoopRunFinished || run_result == kCFRunLoopRunStopped) {
            stop_reason = run_result == kCFRunLoopRunFinished ?
                          "run_loop_finished" : "run_loop_stopped";
            break;
        }
        now = mc_monotonic_seconds();
        mc_print_status(&monitor, true, true,
                        now < 0.0 ? (double)seconds : now - started_monotonic,
                        started_wall, 0, "running", 0);
    }
    if (monitor.stopped_by_limit) {
        stop_reason = "event_limit";
    } else if (mc_stop_requested) {
        stop_reason = "signal";
    }
    exit_code = 0;

cleanup:
    if (client != NULL && registered) {
        unregister_callback(client);
    }
    if (client != NULL && scheduled) {
        unschedule_client(client, run_loop, mode);
    }
    if (client != NULL) {
        CFRelease(client);
    }
    if (io != NULL) {
        dlclose(io);
    }
    if (ready) {
        double elapsed = mc_monotonic_seconds() - started_monotonic;
        mc_print_status(&monitor, true, false, elapsed, started_wall,
                        time(NULL), stop_reason, teardown_errors);
    }
    return exit_code;
}
