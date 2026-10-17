import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "device_hid_aggregate_probe", ROOT / "device_hid_aggregate_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class AggregateProbeTests(unittest.TestCase):
    def test_collects_only_root_event_type_counts(self):
        types = {1: 11, 2: 3, 3: 11, 4: 70}
        result = probe.Aggregates()
        for event in (1, 2, 3, 4):
            result.add(event, types.__getitem__)
        summary = result.summary(0.25, 0)
        self.assertEqual(summary["rootTypes"], {"3": 1, "11": 2})
        self.assertEqual(summary["unknownRootTypes"], 1)
        self.assertNotIn("coordinates", summary)
        self.assertNotIn("text", summary)

    def test_counts_child_types_within_bounded_tree(self):
        event_types = {1: 7, 2: 11, 3: 20, 4: 3}
        arrays = {1: 101, 3: 103}
        members = {101: (2, 3), 103: (4,)}
        result = probe.Aggregates()
        result.add(1, event_types.__getitem__, arrays.get,
                   lambda array: len(members[array]),
                   lambda array, index: members[array][index],
                   lambda _array: 99, 99)
        summary = result.summary(0.1, 0)
        self.assertEqual(summary["rootTypes"], {"7": 1})
        self.assertEqual(summary["childTypes"], {"3": 1, "11": 1, "20": 1})
        self.assertEqual(summary["childTraversalErrors"], 0)
        self.assertFalse(any(key in summary for key in ("coordinates", "values", "text")))

    def test_malformed_or_over_limit_child_tree_fails_closed_without_partial_counts(self):
        cases = (
            (lambda _event: 20, lambda _array: 99, 98, lambda _array, _i: 0),
            (lambda _event: 20, lambda _array: probe.MAX_CHILDREN_PER_EVENT + 1,
             99, lambda _array, _i: 0),
            (lambda _event: 20, lambda _array: 1, 99, lambda _array, _i: 0),
        )
        for get_children, array_count, array_type, array_value in cases:
            with self.subTest(array_type=array_type, count=array_count(1)):
                result = probe.Aggregates()
                result.add(1, lambda _event: 7, get_children, array_count,
                           array_value, lambda _array: 99, array_type)
                summary = result.summary(0.1, 0)
                self.assertEqual(summary["childTypes"], {})
                self.assertEqual(summary["unknownChildTypes"], 0)
                self.assertEqual(summary["childTraversalErrors"], 1)

    def test_child_tree_enforces_total_node_and_depth_bounds(self):
        # Each event has one child; the chain exceeds the supported depth.
        result = probe.Aggregates()
        result.add(1, lambda event: event,
                   lambda event: event if event < 8 else 0,
                   lambda _array: 1,
                   lambda array, _index: array + 1,
                   lambda _array: 99, 99)
        summary = result.summary(0.1, 0)
        self.assertEqual(summary["childTypes"], {})
        self.assertEqual(summary["childTraversalErrors"], 1)

        oversized = probe.Aggregates()
        oversized.add(1, lambda _event: 7, lambda _event: 1,
                      lambda _array: probe.MAX_TREE_NODES,
                      lambda _array, index: index + 1,
                      lambda _array: 99, 99)
        self.assertEqual(oversized.child_traversal_errors, 1)
        self.assertEqual(sum(oversized.child_types), 0)

    def test_aggregates_use_fixed_size_type_counters(self):
        result = probe.Aggregates()
        self.assertEqual(len(result.root_types), probe.TYPE_LIMIT)
        self.assertEqual(result.events, 0)

    def test_duration_and_event_limits_are_validated_before_monitoring(self):
        for duration in (0, probe.MAX_DURATION_SECONDS + 1, float("nan"), True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                probe.run_probe(duration)
        for count in (0, probe.MAX_EVENTS + 1, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                probe.run_probe(max_events=count)

    def test_status_is_atomically_replaced_with_small_aggregate_fields(self):
        aggregates = probe.Aggregates()
        aggregates.root_types[11] = 4
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "status.json"
            path.write_text('{"old":true}', encoding="utf-8")
            payload = probe._status_payload(
                aggregates, ready=True, running=True, started_at=123.0,
                ended_at=None, callback_errors=0, callback_limit_reached=False,
                teardown_errors=[])
            probe._atomic_write_status(path, payload)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(stored["ready"])
            self.assertTrue(stored["running"])
            self.assertEqual(stored["rootTypes"], {"11": 4})
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [path])
            self.assertFalse(any(key in stored for key in ("coordinates", "values", "text")))

    def test_status_writer_rejects_non_finite_json_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "status.json"
            with self.assertRaises(ValueError):
                probe._atomic_write_status(path, {"bad": float("nan")})
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])

    def test_five_minute_window_is_the_maximum(self):
        self.assertEqual(probe.MAX_DURATION_SECONDS, 300.0)
        with self.assertRaises(ValueError):
            probe.run_probe(300.1)

    @unittest.skipIf(sys.platform == "darwin",
                     "host device probe is intentionally not started by unit tests")
    def test_host_execution_refuses_to_start_monitor(self):
        with self.assertRaisesRegex(RuntimeError, "device-only"):
            probe.run_probe(0.1, 1)


if __name__ == "__main__":
    unittest.main()
