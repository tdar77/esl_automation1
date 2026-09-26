"""Bounded, incremental parser for ESL telemetry. No GUI dependencies."""
import json
import re

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_TAGS = 128 * 255


def uint(value, maximum=0xFFFFFFFF):
    return type(value) is int and 0 <= value <= maximum


class SnapshotParser:
    def __init__(self):
        self.buffer = bytearray()
        self.pending = None
        self.rows = {}
        self.errors = 0

    def cancel(self):
        self.pending = None
        self.rows = {}

    def feed(self, data):
        self.buffer.extend(data)
        results = []
        while b"\n" in self.buffer:
            line, _, self.buffer = self.buffer.partition(b"\n")
            text = ANSI.sub("", line.decode("utf-8", errors="replace"))
            marker = text.find("@ESL ")
            if marker < 0:
                continue
            try:
                result = self.record(json.loads(text[marker + 5:]))
                if result is not None:
                    results.append(result)
            except (ValueError, TypeError, KeyError):
                self.errors += 1
                self.cancel()
        if len(self.buffer) > 8192:
            self.buffer.clear()
            self.errors += 1
            self.cancel()
        return results

    def record(self, obj):
        if not isinstance(obj, dict) or obj.get("v") != 1 or not uint(obj.get("id")):
            raise ValueError("Unsupported or malformed record")
        kind = obj.get("type")
        if kind == "begin":
            self.cancel()
            for field in ("session", "uptime_ms", "count", "capacity", "dropped"):
                if not uint(obj.get(field)):
                    raise ValueError(field)
            if not 0 <= obj["count"] <= obj["capacity"] <= MAX_TAGS:
                raise ValueError("capacity")
            self.pending = obj
        elif self.pending is None:
            return None
        elif obj["id"] != self.pending["id"]:
            raise ValueError("Snapshot ID mismatch")
        elif kind == "tag":
            for field in ("group", "tag", "ping_requests", "gatt_responses"):
                if not uint(obj.get(field), 255 if field in ("group", "tag") else 0xFFFFFFFF):
                    raise ValueError(field)
            for field in ("ping_age_ms", "gatt_response_age_ms", "image"):
                if field not in obj or (obj[field] is not None and not uint(obj[field], 255 if field == "image" else 0xFFFFFFFF)):
                    raise ValueError(field)
            key = (obj["group"], obj["tag"])
            if key in self.rows or len(self.rows) >= self.pending["count"]:
                raise ValueError("Duplicate or excess tag")
            self.rows[key] = obj
        elif kind == "end":
            if obj.get("count") != self.pending["count"] or len(self.rows) != obj["count"]:
                raise ValueError("Incomplete snapshot")
            result = {**self.pending, "tags": list(self.rows.values())}
            self.cancel()
            return result
        else:
            raise ValueError("Unknown record")
        return None


def demo_snapshot(tick):
    """Demo is deliberately synthetic and includes only measured schema fields."""
    return {"v": 1, "type": "begin", "id": tick, "session": 123,
            "uptime_ms": tick * 2000, "count": 2, "capacity": 2, "dropped": 0,
            "tags": [{"v": 1, "type": "tag", "id": tick, "group": 0, "tag": tag,
                      "ping_requests": tick + tag, "ping_age_ms": 100 + tag * 400,
                      "image": tag, "gatt_responses": tick if tag == 0 else 0,
                      "gatt_response_age_ms": 80 if tag == 0 else None}
                     for tag in range(2)]}
