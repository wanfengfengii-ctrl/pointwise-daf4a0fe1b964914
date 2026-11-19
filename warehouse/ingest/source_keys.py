from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePosition:
    batch_id: str
    index: int


def validate_source_key(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f'{field} must be a nonempty string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must be valid UTF-8 text') from exc
    return value


def index_source_positions(
    batch_id: str, observations: Sequence[object]
) -> tuple[SourcePosition, ...]:
    return tuple(SourcePosition(batch_id, index) for index, _ in enumerate(observations))
