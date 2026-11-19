def require_integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f'{field} must be an integer')
    return value


def encode_integer(value: int) -> str:
    return format(require_integer(value, 'stored value'), 'x')


def decode_integer(text: str) -> int:
    return int(text, 16)
