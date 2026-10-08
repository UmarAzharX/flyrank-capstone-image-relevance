import unittest
from unittest.mock import Mock, call, patch

from google.genai import errors

from app.retries import call_with_gemini_retries


def api_error(code: int) -> errors.APIError:
    return errors.APIError(
        code,
        {"error": {"message": "Simulated error"}},
    )


class RetryChecks(unittest.TestCase):
    @patch("app.retries.sleep")
    def test_temporary_errors_then_success(self, mocked_sleep):
        operation = Mock(
            side_effect=[api_error(503), api_error(503), "success"]
        )
        notify = Mock()

        result = call_with_gemini_retries(operation, on_retry=notify)

        self.assertEqual(result, "success")
        self.assertEqual(operation.call_count, 3)
        self.assertEqual(
            mocked_sleep.call_args_list,
            [call(2), call(4)],
        )
        self.assertEqual(
            notify.call_args_list,
            [call(2, 503), call(3, 503)],
        )

    @patch("app.retries.sleep")
    def test_invalid_request_stops_immediately(self, mocked_sleep):
        operation = Mock(side_effect=api_error(400))

        with self.assertRaises(errors.APIError):
            call_with_gemini_retries(operation)

        self.assertEqual(operation.call_count, 1)
        mocked_sleep.assert_not_called()

    @patch("app.retries.sleep")
    def test_retries_stop_at_limit(self, mocked_sleep):
        operation = Mock(side_effect=api_error(503))

        with self.assertRaises(errors.APIError):
            call_with_gemini_retries(operation)

        self.assertEqual(operation.call_count, 3)
        self.assertEqual(mocked_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()