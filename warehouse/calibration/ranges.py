"""Collector sequence ranges and their fixed-day publication."""
from collections.abc import Iterable
from dataclasses import dataclass
from sqlite3 import Connection

from ..ingest.observations import read_day_observations
from ..ingest.source_keys import validate_source_key
from ..ledger.day_index import advance_day_head, get_day_head, validate_day_key
from ..ledger.integer_storage import decode_integer, encode_integer, require_integer
from ..ledger.revisions import append_revision, require_revision
from ..ledger.transactions import atomic_write

Interval = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class RangeTicket:
    group_id: str
    ticket_id: str
    lo: int
    hi: int
    priority: int
    offset: int


def create_range_schema(db: Connection) -> None:
    db.execute(
        '''
        CREATE TABLE IF NOT EXISTS range_offset_events (
            revision INTEGER NOT NULL REFERENCES revisions(revision),
            day TEXT NOT NULL,
            group_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('set', 'revoke')),
            lo_hex TEXT,
            hi_hex TEXT,
            priority_hex TEXT,
            offset_hex TEXT,
            PRIMARY KEY (revision, group_id, ticket_id)
        )
        '''
    )
    db.execute(
        'CREATE INDEX IF NOT EXISTS range_events_by_day ON range_offset_events(day, revision)'
    )


def parse_interval(value: object) -> Interval | None:
    """Accept the documented four-tuple, or None for a revocation."""
    if value is None:
        return None
    if not isinstance(value, tuple) or len(value) != 4:
        raise ValueError('interval must be a (lo, hi, priority, offset) tuple')
    lo, hi, priority, offset = value
    for field, number in (
        ('range lower bound', lo),
        ('range upper bound', hi),
        ('range priority', priority),
        ('range offset', offset),
    ):
        require_integer(number, field)
    if not 0 <= lo < hi:
        raise ValueError('range bounds must satisfy 0 <= lo < hi')
    return lo, hi, priority, offset


def _merge(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def _intersection(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if lo < hi:
            result.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result


def _subtract(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = []
    j = 0
    for lo, hi in a:
        while j < len(b) and b[j][1] <= lo:
            j += 1
        current = lo
        k = j
        while k < len(b) and b[k][0] < hi:
            block_lo, block_hi = b[k]
            if block_lo > current:
                result.append((current, min(block_lo, hi)))
            current = max(current, block_hi)
            if current >= hi:
                break
            k += 1
        if current < hi:
            result.append((current, hi))
    return result


def validate_no_ambiguity(tickets: Iterable[RangeTicket]) -> None:
    """Every covered integer sequence must resolve to one highest-layer offset."""
    by_priority: dict[int, list[RangeTicket]] = {}
    for ticket in tickets:
        by_priority.setdefault(ticket.priority, []).append(ticket)

    covered_by_higher: list[tuple[int, int]] = []
    for priority in sorted(by_priority, reverse=True):
        level = by_priority[priority]
        by_offset: dict[int, list[tuple[int, int]]] = {}
        for ticket in level:
            by_offset.setdefault(ticket.offset, []).append((ticket.lo, ticket.hi))
        unions = {offset: _merge(spans) for offset, spans in by_offset.items()}
        offsets = sorted(unions)
        for first in range(len(offsets)):
            for second in range(first + 1, len(offsets)):
                overlap = _intersection(unions[offsets[first]], unions[offsets[second]])
                if _subtract(overlap, covered_by_higher):
                    raise ValueError(
                        'range offsets are ambiguous at the highest priority'
                    )
        covered_by_higher = _merge(covered_by_higher + [(t.lo, t.hi) for t in level])


def read_active_tickets(
    db: Connection, day: str, revision: int, group_id: str | None = None
) -> dict[tuple[str, str], RangeTicket]:
    rows = db.execute(
        '''
        SELECT group_id, ticket_id, action, lo_hex, hi_hex, priority_hex, offset_hex
        FROM range_offset_events
        WHERE day = ? AND revision <= ?
        ORDER BY revision
        ''',
        (day, revision),
    )
    active: dict[tuple[str, str], RangeTicket] = {}
    for stored_group, ticket_id, action, lo, hi, priority, offset in rows:
        key = (stored_group, ticket_id)
        if action == 'revoke':
            active.pop(key, None)
        else:
            active[key] = RangeTicket(
                stored_group,
                ticket_id,
                decode_integer(lo),
                decode_integer(hi),
                decode_integer(priority),
                decode_integer(offset),
            )
    if group_id is not None:
        active = {key: value for key, value in active.items() if key[0] == group_id}
    return active


def read_range_tickets(
    db: Connection, day: str, revision: int
) -> dict[str, tuple[RangeTicket, ...]]:
    by_group: dict[str, list[RangeTicket]] = {}
    for ticket in read_active_tickets(db, day, revision).values():
        by_group.setdefault(ticket.group_id, []).append(ticket)
    return {group_id: tuple(items) for group_id, items in by_group.items()}


def range_offset_for(tickets: Iterable[RangeTicket], sequence: int | None) -> int | None:
    if sequence is None:
        return None
    best: RangeTicket | None = None
    for ticket in tickets:
        if ticket.lo <= sequence < ticket.hi:
            if best is None or ticket.priority > best.priority:
                best = ticket
    return None if best is None else best.offset


def _write_event(
    db: Connection,
    day: str,
    revision: int,
    group_id: str,
    ticket_id: str,
    interval: Interval | None,
) -> None:
    if interval is None:
        db.execute(
            '''
            INSERT INTO range_offset_events
                (revision, day, group_id, ticket_id, action)
            VALUES (?, ?, ?, ?, 'revoke')
            ''',
            (revision, day, group_id, ticket_id),
        )
        return
    lo, hi, priority, offset = interval
    db.execute(
        '''
        INSERT INTO range_offset_events
            (revision, day, group_id, ticket_id, action, lo_hex, hi_hex,
             priority_hex, offset_hex)
        VALUES (?, ?, ?, ?, 'set', ?, ?, ?, ?)
        ''',
        (
            revision,
            day,
            group_id,
            ticket_id,
            encode_integer(lo),
            encode_integer(hi),
            encode_integer(priority),
            encode_integer(offset),
        ),
    )


def set_range_offset(
    db: Connection,
    day: str,
    expected_revision: int,
    group_id: str,
    ticket_id: str,
    interval: Interval | None,
) -> int:
    day = validate_day_key(day)
    expected_revision = require_integer(expected_revision, 'expected_revision')
    group_id = validate_source_key(group_id, 'group_id')
    ticket_id = validate_source_key(ticket_id, 'ticket_id')
    parsed = parse_interval(interval)

    with atomic_write(db):
        head = get_day_head(db, day)
        if head != expected_revision:
            raise ValueError(
                f'expected revision {expected_revision} is not the current head for {day}'
            )
        require_revision(db, expected_revision)

        visible_groups = {
            observation.group_id
            for observation in read_day_observations(db, day, expected_revision)
        }
        if group_id not in visible_groups:
            raise ValueError(f'group is not visible on this day: {group_id!r}')

        active = read_active_tickets(db, day, expected_revision, group_id)
        key = (group_id, ticket_id)
        if parsed is None:
            if key not in active:
                raise ValueError(f'ticket is not active: {ticket_id!r}')
            del active[key]
        else:
            if key in active:
                raise ValueError(f'ticket is already active: {ticket_id!r}')
            active[key] = RangeTicket(group_id, ticket_id, *parsed)

        validate_no_ambiguity(active.values())

        # Range publications share the explicit-correction revision kind so
        # stores created before ranges existed keep a compatible schema.
        revision = append_revision(db, day, 'correction')
        _write_event(db, day, revision, group_id, ticket_id, parsed)
        advance_day_head(db, day, revision)
        return revision


def read_range_audit(db: Connection, revision: int) -> tuple[tuple[str, str, Interval | None], ...]:
    """Return the ticket actions recorded by one revision, in key order."""
    rows = db.execute(
        '''
        SELECT group_id, ticket_id, action, lo_hex, hi_hex, priority_hex, offset_hex
        FROM range_offset_events WHERE revision = ?
        ORDER BY group_id COLLATE BINARY, ticket_id COLLATE BINARY
        ''',
        (revision,),
    ).fetchall()
    audit = []
    for group_id, ticket_id, action, lo, hi, priority, offset in rows:
        if action == 'revoke':
            audit.append((group_id, ticket_id, None))
        else:
            audit.append(
                (
                    group_id,
                    ticket_id,
                    (
                        decode_integer(lo),
                        decode_integer(hi),
                        decode_integer(priority),
                        decode_integer(offset),
                    ),
                )
            )
    return tuple(audit)
