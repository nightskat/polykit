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

PAID_MODEL = "openrouter/deepseek/deepseek-v4-pro"


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

        res = or_dispatch("hello", model=PAID_MODEL, key="fake-key", opener=fake_opener)
        self.assertTrue(res.ok)
        self.assertEqual(res.text, "hi")

    def test_or_dispatch_no_key(self) -> None:
        import bin.lib.openrouter
        orig = bin.lib.openrouter.get_or_key
        bin.lib.openrouter.get_or_key = lambda env=None: None
        try:
            res = or_dispatch("hello", model=PAID_MODEL, key=None)
            self.assertFalse(res.ok)
            self.assertIn("OPENROUTER_API_KEY", res.error or "")
        finally:
            bin.lib.openrouter.get_or_key = orig

    def test_or_dispatch_402(self) -> None:
        def fake_opener_402(req: any, timeout: int) -> None:
            fp = io.BytesIO(b"quota exceeded")
            raise urllib.error.HTTPError("https://openrouter.ai", 402, "Payment Required", {}, fp)

        res = or_dispatch("hello", model=PAID_MODEL, key="fake-key", opener=fake_opener_402)
        self.assertFalse(res.ok)
        self.assertTrue(res.quota_capped)
        self.assertEqual(res.http_code, 402)

    def test_or_dispatch_500(self) -> None:
        def fake_opener_500(req: any, timeout: int) -> None:
            fp = io.BytesIO(b"internal error")
            raise urllib.error.HTTPError("https://openrouter.ai", 500, "Internal Error", {}, fp)

        res = or_dispatch("hello", model=PAID_MODEL, key="fake-key", opener=fake_opener_500)
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

        # Policy mới cấm OpenRouter auto/router unresolved; phải bị chặn trước khi gọi opener
        res = or_dispatch("hello", model="auto", key="fake-key", opener=fake_opener)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "openrouter_unresolved_destination")
        self.assertIn("openrouter_unresolved_destination", res.error or "")
        self.assertEqual(len(captured_req), 0)

    def test_or_dispatch_effort_param(self) -> None:
        captured_req = []

        class FakeResponse:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"hi"}}]}'

        def fake_opener(req: any, timeout: int) -> FakeResponse:
            captured_req.append(req)
            return FakeResponse()

        res = or_dispatch("hello", model=PAID_MODEL, effort="xhigh", key="fake-key", opener=fake_opener)
        self.assertTrue(res.ok)
        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        data = json.loads(req.data.decode("utf-8"))
        self.assertEqual(data["model"], "deepseek/deepseek-v4-pro")
        self.assertEqual(data["reasoning"], {"effort": "xhigh"})

    def test_or_dispatch_effort_env(self) -> None:
        captured_req = []

        class FakeResponse:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"hi"}}]}'

        def fake_opener(req: any, timeout: int) -> FakeResponse:
            captured_req.append(req)
            return FakeResponse()

        import os
        orig = os.environ.get("OPENROUTER_REASONING_EFFORT")
        os.environ["OPENROUTER_REASONING_EFFORT"] = "high"
        try:
            res = or_dispatch("hello", model=PAID_MODEL, key="fake-key", opener=fake_opener)
            self.assertTrue(res.ok)
            self.assertEqual(len(captured_req), 1)
            req = captured_req[0]
            data = json.loads(req.data.decode("utf-8"))
            self.assertEqual(data["reasoning"], {"effort": "high"})
        finally:
            if orig is not None:
                os.environ["OPENROUTER_REASONING_EFFORT"] = orig
            else:
                os.environ.pop("OPENROUTER_REASONING_EFFORT", None)

    def test_or_dispatch_effort_precedence(self) -> None:
        captured_req = []

        class FakeResponse:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"hi"}}]}'

        def fake_opener(req: any, timeout: int) -> FakeResponse:
            captured_req.append(req)
            return FakeResponse()

        import os
        orig = os.environ.get("OPENROUTER_REASONING_EFFORT")
        os.environ["OPENROUTER_REASONING_EFFORT"] = "low"
        try:
            res = or_dispatch("hello", model=PAID_MODEL, effort="medium", key="fake-key", opener=fake_opener)
            self.assertTrue(res.ok)
            data = json.loads(captured_req[0].data.decode("utf-8"))
            self.assertEqual(data["reasoning"], {"effort": "medium"})
        finally:
            if orig is not None:
                os.environ["OPENROUTER_REASONING_EFFORT"] = orig
            else:
                os.environ.pop("OPENROUTER_REASONING_EFFORT", None)

    def test_or_dispatch_or_effort_env_whitespace(self) -> None:
        captured_req = []

        class FakeResponse:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"hi"}}]}'

        def fake_opener(req: any, timeout: int) -> FakeResponse:
            captured_req.append(req)
            return FakeResponse()

        import os
        orig = os.environ.get("OR_EFFORT")
        os.environ["OR_EFFORT"] = "  xhigh \n"
        try:
            res = or_dispatch("hello", model=PAID_MODEL, key="fake-key", opener=fake_opener)
            self.assertTrue(res.ok)
            data = json.loads(captured_req[0].data.decode("utf-8"))
            self.assertEqual(data["reasoning"], {"effort": "xhigh"})
        finally:
            if orig is not None:
                os.environ["OR_EFFORT"] = orig
            else:
                os.environ.pop("OR_EFFORT", None)

    def test_or_dispatch_effort_invalid(self) -> None:
        res = or_dispatch("hello", model=PAID_MODEL, effort="banana", key="fake-key")
        self.assertFalse(res.ok)
        self.assertIn("effort phải là một trong", res.error)

    def test_or_dispatch_effort_none_omits(self) -> None:
        captured_req = []

        class FakeResponse:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"hi"}}]}'

        def fake_opener(req: any, timeout: int) -> FakeResponse:
            captured_req.append(req)
            return FakeResponse()

        res = or_dispatch("hello", model=PAID_MODEL, effort="none", key="fake-key", opener=fake_opener)
        self.assertTrue(res.ok)
        data = json.loads(captured_req[0].data.decode("utf-8"))
        self.assertNotIn("reasoning", data)

    def test_run_vendor_openrouter_effort_wiring(self) -> None:
        import lib.openrouter as oro
        from lib.dispatcher import run_vendor
        saved = oro.or_dispatch
        captured = []

        def fake_or_dispatch(prompt, model="auto", timeout=120, effort=None, **kwargs):
            captured.append(effort)
            return oro.ORResult(ok=True, text="mock-resp", served_model=model)

        oro.or_dispatch = fake_or_dispatch
        try:
            res = run_vendor(vendor="openrouter", prompt="hi", model=PAID_MODEL, effort="xhigh")
            self.assertEqual(res.status, "ok")
            self.assertEqual(captured, ["xhigh"])
        finally:
            oro.or_dispatch = saved

    def test_or_dispatch_contributor_strictly_blocked(self) -> None:
        # Mock string negative: cấm contributor tuyệt đối, không gọi live
        res = or_dispatch("hello", model="meta/muse-spark-1.3-contributor", key="fake-key")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "contributor_model_blocked")
        self.assertIn("contributor_model_blocked", res.error or "")


if __name__ == "__main__":
    unittest.main()
