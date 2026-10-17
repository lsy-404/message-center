import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "device_hid_aggregate_probe", ROOT / "device_hid_aggregate_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class AggregateProbeTests(unittest.TestCase):
    def test_collects_only_root_and_parent_child_type_counts(self):
        types = {1: 11, 2: 5, 3: 5, 4: 9}
        children = {1: [2, 3], 2: [4], 3: [], 4: []}
        result = probe.Aggregates()
        result.add(1, types.__getitem__, children.__getitem__)
        summary = result.summary(0.25, 0)
        self.assertEqual(summary["rootTypes"], {"11": 1})
        self.assertEqual(summary["childTypePairs"], [
            {"parentType": 5, "childType": 9, "count": 1},
            {"parentType": 11, "childType": 5, "count": 2},
        ])
        self.assertEqual(summary["nodes"], 4)
        self.assertNotIn("coordinates", summary)
        self.assertNotIn("text", summary)

    def test_cycle_and_depth_are_bounded(self):
        types = {index: index for index in range(20)}
        children = {index: [index + 1] for index in range(19)}
        children[19] = [1]
        result = probe.Aggregates()
        result.add(0, types.__getitem__, children.__getitem__)
        self.assertLessEqual(result.nodes, probe.MAX_DEPTH + 1)
        self.assertEqual(result.truncated_events, 1)

    def test_wide_tree_is_bounded(self):
        children = {0: list(range(1, 200))}
        children.update({index: [] for index in range(1, 200)})
        types = {index: index % probe.TYPE_LIMIT for index in range(200)}
        result = probe.Aggregates()
        result.add(0, types.__getitem__, children.__getitem__)
        self.assertLessEqual(result.nodes, probe.MAX_NODES_PER_EVENT)
        self.assertEqual(result.truncated_events, 1)

    def test_duration_and_event_limits_are_validated_before_monitoring(self):
        for duration in (0, probe.MAX_DURATION_SECONDS + 1, float("nan"), True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                probe.run_probe(duration)
        for count in (0, probe.MAX_EVENTS + 1, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                probe.run_probe(max_events=count)

    @unittest.skipIf(sys.platform == "darwin",
                     "host device probe is intentionally not started by unit tests")
    def test_host_execution_refuses_to_start_monitor(self):
        with self.assertRaisesRegex(RuntimeError, "device-only"):
            probe.run_probe(0.1, 1)


if __name__ == "__main__":
    unittest.main()
