from __future__ import annotations

import unittest
import json
import io
import urllib.error
from pathlib import Path
from bin.lib.openrouter import (
    get_or_key,
    or_dispatch,
    ORResult,
    DEFAULT_FREE_MODEL,
    OR_KEY_FILES,
)

class TestOpenRouter(unittest.TestCase):
    def test_get_or_key_env(self) -> None:
        env = {"OPENROUTER_API_KEY": "k1"}
        self.assertEqual(get_or_key(env), "k1")

        env2 = {"OR_API_KEY": "k2"}
        self.assertEqual(get_or_key(env2), "k2")

    def test_get_or_key_empty(self) -> None:
        original = list(OR_KEY_FILES)
        OR_KEY_FILES.clear()
        try:
            self.assertIsNone(get_or_key({}))
        finally:
            OR_KEY_FILES.extend(original)

    def test_or_dispatch_ok(self) -> None:
        class FakeResponse:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"hi"}}]}'

        def fake_opener(req: any, timeout: int) -> FakeResponse:
            return FakeResponse()

        res = or_dispatch("hello", key="fake-key", opener=fake_opener)
        self.assertTrue(res.ok)
        self.assertEqual(res.text, "hi")

    def test_or_dispatch_no_key(self) -> None:
        import bin.lib.openrouter
        orig = bin.lib.openrouter.get_or_key
        bin.lib.openrouter.get_or_key = lambda env=None: None
        try:
            res = or_dispatch("hello", key=None)
            self.assertFalse(res.ok)
            self.assertIn("OPENROUTER_API_KEY", res.error or "")
        finally:
            bin.lib.openrouter.get_or_key = orig

    def test_or_dispatch_402(self) -> None:
        def fake_opener_402(req: any, timeout: int) -> None:
            fp = io.BytesIO(b"quota exceeded")
            raise urllib.error.HTTPError("https://openrouter.ai", 402, "Payment Required", {}, fp)

        res = or_dispatch("hello", key="fake-key", opener=fake_opener_402)
        self.assertFalse(res.ok)
        self.assertTrue(res.quota_capped)
        self.assertEqual(res.http_code, 402)

    def test_or_dispatch_500(self) -> None:
        def fake_opener_500(req: any, timeout: int) -> None:
            fp = io.BytesIO(b"internal error")
            raise urllib.error.HTTPError("https://openrouter.ai", 500, "Internal Error", {}, fp)

        res = or_dispatch("hello", key="fake-key", opener=fake_opener_500)
        self.assertFalse(res.ok)
        self.assertFalse(res.quota_capped)
        self.assertEqual(res.http_code, 500)

    def test_or_dispatch_model_auto(self) -> None:
        captured_req = []

        class FakeResponse:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"hi"}}]}'

        def fake_opener(req: any, timeout: int) -> FakeResponse:
            captured_req.append(req)
            return FakeResponse()

        res = or_dispatch("hello", model="auto", key="fake-key", opener=fake_opener)
        self.assertTrue(res.ok)
        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        data = json.loads(req.data.decode("utf-8"))
        self.assertEqual(data["model"], DEFAULT_FREE_MODEL)

if __name__ == "__main__":
    unittest.main()
