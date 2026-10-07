"""Bounded per-conversation cursors for sources that page from newest to oldest."""

import copy
import json


MAX_CONVERSATIONS = 200
MAX_SOURCE_ID_LENGTH = 256
MAX_CURSOR_BYTES = 65_536


class SourceCursorError(ValueError):
    pass


def _conversation_id(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise SourceCursorError("invalid_conversation_id")
    return value


def _check_size(cursor):
    try:
        size = len(json.dumps(cursor, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise SourceCursorError("invalid_cursor")
    if size > MAX_CURSOR_BYTES:
        raise SourceCursorError("cursor_too_large")
    return cursor


def new_cursor():
    return {"version": 1, "conversations": {}}


def _copy_cursor(cursor):
    if cursor is None:
        return new_cursor()
    if (not isinstance(cursor, dict) or cursor.get("version") != 1 or
            not isinstance(cursor.get("conversations"), dict) or
            len(cursor["conversations"]) > MAX_CONVERSATIONS):
        raise SourceCursorError("invalid_cursor")
    result = copy.deepcopy(cursor)
    for conversation_id, state in result["conversations"].items():
        if (not isinstance(conversation_id, str) or not conversation_id or
                len(conversation_id) > 256 or not isinstance(state, dict) or
                set(state) != {"initialized", "committedHead", "sweepHead", "before"} or
                state.get("initialized") is not True):
            raise SourceCursorError("invalid_conversation_cursor")
        for key in ("committedHead", "sweepHead", "before"):
            value = state.get(key)
            if value is not None:
                _source_id(value)
        if (state.get("sweepHead") is None and state.get("before") is not None) or (
                state.get("sweepHead") is not None and state.get("sweepHead") == state.get("committedHead")):
            raise SourceCursorError("invalid_conversation_cursor")
    return _check_size(result)


def _source_id(value):
    if not isinstance(value, str) or not value or len(value) > MAX_SOURCE_ID_LENGTH:
        raise SourceCursorError("invalid_source_id")
    return value


def _records(records, page_limit):
    if (isinstance(page_limit, bool) or not isinstance(page_limit, int) or
            page_limit < 1 or page_limit > 20):
        raise SourceCursorError("invalid_page_limit")
    if not isinstance(records, list) or len(records) > page_limit:
        raise SourceCursorError("invalid_page")
    normalized = []
    ids = set()
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("event"), dict):
            raise SourceCursorError("invalid_page_record")
        source_id = _source_id(item.get("sourceId"))
        if source_id in ids:
            raise SourceCursorError("duplicate_source_id")
        ids.add(source_id)
        normalized.append({"sourceId": source_id, "event": item["event"]})
    return normalized


def initialize_baseline(cursor, conversation_id, head, records, page_limit=20):
    """Set the first observed page as the baseline and return its events once."""
    conversation_id = _conversation_id(conversation_id)
    current = _copy_cursor(cursor)
    if conversation_id in current["conversations"]:
        raise SourceCursorError("baseline_already_initialized")
    page = _records(records, page_limit)
    baseline_head = None if head is None else _source_id(head)
    if baseline_head is None and page:
        raise SourceCursorError("baseline_head_missing")
    if baseline_head is not None and baseline_head not in {item["sourceId"] for item in page}:
        raise SourceCursorError("baseline_head_not_in_page")
    current["conversations"][conversation_id] = {
        "initialized": True,
        "committedHead": baseline_head,
        "sweepHead": None,
        "before": None,
    }
    return _check_size(current), [item["event"] for item in page]


def begin_sweep(cursor, conversation_id, latest_head):
    """Freeze a high-water head; messages newer than it belong to the next sweep."""
    conversation_id = _conversation_id(conversation_id)
    current = _copy_cursor(cursor)
    state = current["conversations"].get(conversation_id)
    if state is None or state.get("initialized") is not True:
        raise SourceCursorError("baseline_required")
    if state.get("sweepHead") is not None:
        return current
    if latest_head is None:
        if state.get("committedHead") is not None:
            raise SourceCursorError("source_head_missing")
        return current
    head = _source_id(latest_head)
    if head == state.get("committedHead"):
        return current
    state["sweepHead"] = head
    state["before"] = None
    return _check_size(current)


def accept_page(cursor, conversation_id, records, page_limit=20, reached_beginning=False, has_more=None):
    """Apply one newest-to-oldest page, dropping an inclusive continuation anchor."""
    conversation_id = _conversation_id(conversation_id)
    current = _copy_cursor(cursor)
    state = current["conversations"].get(conversation_id)
    if state is None or state.get("sweepHead") is None:
        raise SourceCursorError("sweep_not_started")
    page = _records(records, page_limit)
    if not isinstance(reached_beginning, bool):
        raise SourceCursorError("invalid_page_completion")
    if has_more is not None and not isinstance(has_more, bool):
        raise SourceCursorError("invalid_page_completion")
    if reached_beginning and has_more is True:
        raise SourceCursorError("invalid_page_completion")

    before = state.get("before")
    if before is None:
        if not page or page[0]["sourceId"] != state["sweepHead"]:
            raise SourceCursorError("sweep_head_not_first")
    else:
        if not page or page[0]["sourceId"] != before:
            raise SourceCursorError("inclusive_anchor_missing")
        page = page[1:]

    source_ids = [item["sourceId"] for item in page]
    if before is not None and state["sweepHead"] in source_ids:
        raise SourceCursorError("sweep_head_repeated")
    committed_head = state.get("committedHead")
    if committed_head is not None and committed_head in source_ids:
        boundary = source_ids.index(committed_head)
        events = [item["event"] for item in page[:boundary]]
        state["committedHead"] = state["sweepHead"]
        state["sweepHead"] = None
        state["before"] = None
        return _check_size(current), events, True

    if reached_beginning:
        if committed_head is not None:
            raise SourceCursorError("committed_head_missing")
        events = [item["event"] for item in page]
        state["committedHead"] = state["sweepHead"]
        state["sweepHead"] = None
        state["before"] = None
        return _check_size(current), events, True

    if not page:
        raise SourceCursorError("page_made_no_progress")
    if has_more is not True:
        raise SourceCursorError("incomplete_page")
    state["before"] = page[-1]["sourceId"]
    return _check_size(current), [item["event"] for item in page], False
