import time
import uuid
import os


def generate_uuid7() -> str:
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")

    uuid_int = (ts_ms & 0xFFFFFFFFFFFF) << 80
    uuid_int |= 0x7 << 76
    uuid_int |= ((rand >> 62) & 0xFFF) << 64
    uuid_int |= 0b10 << 62
    uuid_int |= rand & 0x3FFFFFFFFFFFFFFF

    return str(uuid.UUID(int=uuid_int))


def classify_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    else:
        return "senior"
