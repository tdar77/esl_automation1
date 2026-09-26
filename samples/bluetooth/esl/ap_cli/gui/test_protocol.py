import json
import unittest

from protocol import SnapshotParser, demo_snapshot


def wire(snapshot):
    records = [snapshot, *snapshot['tags'], {'v': 1, 'type': 'end',
               'id': snapshot['id'], 'count': snapshot['count']}]
    return ''.join('@ESL ' + json.dumps(r) + '\r\n' for r in records).encode()


class ProtocolTests(unittest.TestCase):
    def test_fragmented_with_console_noise(self):
        parser = SnapshotParser()
        data = b'\x1b[32muart:~$ esl_ap log json\r\n' + wire(demo_snapshot(2))
        results = []
        for byte in data:
            results.extend(parser.feed(bytes([byte])))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['tags'][1]['gatt_response_age_ms'], None)

    def test_empty_snapshot(self):
        snapshot = demo_snapshot(1)
        snapshot.update(count=0, tags=[])
        self.assertEqual(SnapshotParser().feed(wire(snapshot))[0]['tags'], [])

    def test_missing_tag_rejected_and_next_snapshot_recovers(self):
        snapshot = demo_snapshot(1)
        snapshot['tags'].pop()
        parser = SnapshotParser()
        self.assertEqual(parser.feed(wire(snapshot)), [])
        self.assertEqual(parser.errors, 1)
        self.assertEqual(len(parser.feed(wire(demo_snapshot(2)))), 1)

    def test_duplicate_tag_rejected(self):
        snapshot = demo_snapshot(1)
        snapshot['tags'][1] = snapshot['tags'][0]
        self.assertEqual(SnapshotParser().feed(wire(snapshot)), [])

    def test_id_mismatch_rejected(self):
        snapshot = demo_snapshot(1)
        snapshot['tags'][0]['id'] = 2
        self.assertEqual(SnapshotParser().feed(wire(snapshot)), [])

    def test_invalid_field_types(self):
        for value in (True, -1, '2', [], 2**32):
            snapshot = demo_snapshot(1)
            snapshot['tags'][0]['ping_requests'] = value
            self.assertEqual(SnapshotParser().feed(wire(snapshot)), [])

    def test_malformed_json_cancels_partial_snapshot(self):
        parser = SnapshotParser()
        parser.feed(b'@ESL {bad json}\n')
        self.assertEqual(parser.errors, 1)
        self.assertEqual(len(parser.feed(wire(demo_snapshot(1)))), 1)

    def test_unterminated_noise_is_bounded(self):
        parser = SnapshotParser()
        parser.feed(b'x' * 9000)
        self.assertLessEqual(len(parser.buffer), 8192)


if __name__ == '__main__':
    unittest.main()
