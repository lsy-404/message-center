import importlib.util
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "bridge", "device-runtime", "source_cursor.py")
SPEC = importlib.util.spec_from_file_location("source_cursor", SOURCE)
source_cursor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source_cursor)


def records(*ids):
    return [{"sourceId": str(ident), "event": {"externalId": "profile:message-%s" % ident}}
            for ident in ids]


class SourceCursorTests(unittest.TestCase):
    def test_initial_baseline_emits_bounded_latest_page_and_sets_head(self):
        cursor, events = source_cursor.initialize_baseline(
            None, "conversation-a", "20", records(*range(20, 0, -1)))
        state = cursor["conversations"]["conversation-a"]
        self.assertEqual(20, len(events))
        self.assertEqual("20", state["committedHead"])
        self.assertIsNone(state["sweepHead"])

    def test_empty_baseline_can_collect_messages_until_history_beginning(self):
        cursor, events = source_cursor.initialize_baseline(None, "conversation-a", None, [])
        self.assertEqual([], events)
        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "2")
        cursor, page_events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("2", "1"), page_limit=2, has_more=True)
        self.assertEqual(["profile:message-2", "profile:message-1"],
                         [event["externalId"] for event in page_events])
        self.assertFalse(done)
        cursor, page_events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("1"), page_limit=2,
            reached_beginning=True, has_more=False)
        self.assertEqual([], page_events)
        self.assertTrue(done)
        self.assertEqual("2", cursor["conversations"]["conversation-a"]["committedHead"])

    def test_frozen_head_paginates_backward_and_defers_newer_messages(self):
        cursor, baseline = source_cursor.initialize_baseline(
            None, "conversation-a", "2", records("2", "1"))
        self.assertEqual(2, len(baseline))
        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "6")
        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "7")
        self.assertEqual("6", cursor["conversations"]["conversation-a"]["sweepHead"])

        cursor, first_events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("6", "5", "4"), page_limit=3, has_more=True)
        self.assertFalse(done)
        self.assertEqual(["profile:message-6", "profile:message-5", "profile:message-4"],
                         [event["externalId"] for event in first_events])
        self.assertEqual("4", cursor["conversations"]["conversation-a"]["before"])

        cursor, tail_events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("4", "3", "2"), page_limit=3, has_more=True)
        self.assertTrue(done)
        self.assertEqual(["profile:message-3"], [event["externalId"] for event in tail_events])
        state = cursor["conversations"]["conversation-a"]
        self.assertEqual("6", state["committedHead"])
        self.assertIsNone(state["sweepHead"])

        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "7")
        cursor, events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("7", "6", "5"), page_limit=3, has_more=True)
        self.assertTrue(done)
        self.assertEqual(["profile:message-7"], [event["externalId"] for event in events])
        self.assertEqual("7", cursor["conversations"]["conversation-a"]["committedHead"])

    def test_inclusive_anchor_is_removed_and_short_page_needs_explicit_completion(self):
        cursor, _ = source_cursor.initialize_baseline(None, "conversation-a", "10", records("10"))
        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "13")
        cursor, _, done = source_cursor.accept_page(
            cursor, "conversation-a", records("13", "12", "11"), page_limit=3, has_more=True)
        self.assertFalse(done)
        prior = cursor
        with self.assertRaisesRegex(source_cursor.SourceCursorError, "incomplete_page"):
            source_cursor.accept_page(
                cursor, "conversation-a", records("11", "9"), page_limit=3, has_more=False)
        self.assertEqual(prior, cursor, "a failed page must leave the committed input cursor untouched")

        cursor, events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("11", "10"), page_limit=3, has_more=True)
        self.assertTrue(done)
        self.assertEqual([], events, "the inclusive anchor was already emitted in the prior page")

    def test_missing_old_head_or_repeated_anchor_fails_without_advancing(self):
        cursor, _ = source_cursor.initialize_baseline(None, "conversation-a", "5", records("5"))
        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "8")
        cursor, _, _ = source_cursor.accept_page(
            cursor, "conversation-a", records("8", "7", "6"), page_limit=3, has_more=True)
        prior = cursor
        with self.assertRaisesRegex(source_cursor.SourceCursorError, "page_made_no_progress"):
            source_cursor.accept_page(
                cursor, "conversation-a", records("6"), page_limit=3, has_more=True)
        self.assertEqual(prior, cursor)
        with self.assertRaisesRegex(source_cursor.SourceCursorError, "committed_head_missing"):
            source_cursor.accept_page(
                cursor, "conversation-a", records("6", "4"), page_limit=3,
                reached_beginning=True, has_more=False)
        self.assertEqual(prior, cursor)

    def test_opaque_ids_need_not_be_numerically_or_lexicographically_monotonic(self):
        cursor, _ = source_cursor.initialize_baseline(
            None, "conversation-a", "old-zebra", records("old-zebra"))
        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "new-ant")
        cursor, first_events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("new-ant", "id-91", "id-4"),
            page_limit=3, has_more=True)
        self.assertFalse(done)
        cursor, final_events, done = source_cursor.accept_page(
            cursor, "conversation-a", records("id-4", "old-zebra"),
            page_limit=2, reached_beginning=True, has_more=False)
        self.assertTrue(done)
        self.assertEqual(["profile:message-new-ant", "profile:message-id-91", "profile:message-id-4"],
                         [event["externalId"] for event in first_events + final_events])

    def test_frozen_head_reappearing_in_an_older_page_is_rejected(self):
        cursor, _ = source_cursor.initialize_baseline(None, "conversation-a", "old-head", records("old-head"))
        cursor = source_cursor.begin_sweep(cursor, "conversation-a", "new-head")
        cursor, _, done = source_cursor.accept_page(
            cursor, "conversation-a", records("new-head", "middle"), page_limit=2, has_more=True)
        self.assertFalse(done)
        prior = cursor
        with self.assertRaisesRegex(source_cursor.SourceCursorError, "sweep_head_repeated"):
            source_cursor.accept_page(
                cursor, "conversation-a", records("middle", "new-head", "old-head"),
                page_limit=3, reached_beginning=True, has_more=False)
        self.assertEqual(prior, cursor)

    def test_duplicate_ids_and_pages_over_twenty_are_rejected(self):
        with self.assertRaisesRegex(source_cursor.SourceCursorError, "duplicate_source_id"):
            source_cursor.initialize_baseline(None, "conversation-a", "1", records("1", "1"))
        with self.assertRaisesRegex(source_cursor.SourceCursorError, "invalid_page"):
            source_cursor.initialize_baseline(
                None, "conversation-a", "21", records(*range(21, 0, -1)))


if __name__ == "__main__":
    unittest.main()
