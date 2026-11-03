from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.llm import _is_stream_options_error, _usage_key


class StreamUsageTest(unittest.TestCase):
    """用量统计依赖 stream_options；不支持的端点必须能识别并降级。"""

    def test_detects_stream_options_rejection(self) -> None:
        exc = SimpleNamespace(
            message="Unrecognized request argument supplied: stream_options", body=None
        )
        self.assertTrue(_is_stream_options_error(exc))

    def test_detects_include_usage_variant(self) -> None:
        exc = SimpleNamespace(message="unknown field include_usage", body={})
        self.assertTrue(_is_stream_options_error(exc))

    def test_other_bad_request_is_not_swallowed(self) -> None:
        exc = SimpleNamespace(message="context_length_exceeded", body={"code": "x"})
        self.assertFalse(_is_stream_options_error(exc))

    def test_usage_key_is_stable(self) -> None:
        self.assertEqual(_usage_key("https://api.example.com/v1", "m"), "https://api.example.com/v1|m")
        self.assertEqual(_usage_key(None, "m"), "|m")


if __name__ == "__main__":
    unittest.main()
