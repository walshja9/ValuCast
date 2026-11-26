import http.client
import io
import json
import unittest
from email.message import Message
from urllib.error import HTTPError
from unittest.mock import patch, MagicMock

from scraper.fangraphs import fetch_projections, fetch_all, PROJECTION_URL


class TestFetchProjections(unittest.TestCase):
    def _mock_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode("utf-8")
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("scraper.fangraphs.urlopen")
    def test_fetch_returns_list_of_dicts(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([
            {"PlayerName": "Test Player", "Team": "NYY", "HR": 30, "playerids": "12345"},
        ])
        result = fetch_projections("steamer", "bat")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["PlayerName"], "Test Player")

    @patch("scraper.fangraphs.urlopen")
    def test_fetch_rejects_non_list_payloads(self, mock_urlopen):
        for data in ({}, None, "", 0, False):
            with self.subTest(data=data):
                mock_urlopen.return_value = self._mock_response(data)
                with self.assertRaisesRegex(ValueError, "FanGraphs.*list"):
                    fetch_projections("steamerr", "bat")

    @patch("scraper.fangraphs.urlopen")
    def test_empty_list_is_a_valid_feed(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([])
        self.assertEqual(fetch_projections("steamerr", "bat"), [])

    @patch("scraper.fangraphs.urlopen")
    def test_short_http_body_raises_incomplete_read(self, mock_urlopen):
        class Socket:
            def makefile(self, _mode):
                return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n[]")

        response = http.client.HTTPResponse(Socket())
        response.begin()
        mock_urlopen.return_value = response
        with self.assertRaises(http.client.IncompleteRead):
            fetch_projections("steamerr", "bat")
        mock_urlopen.assert_called_once()

    @patch("scraper.fangraphs.urlopen")
    def test_cut_json_body_raises_decode_error(self, mock_urlopen):
        response = self._mock_response([])
        response.read.return_value = b'[{"PlayerName":'
        mock_urlopen.return_value = response
        with self.assertRaises(json.JSONDecodeError):
            fetch_projections("steamerr", "bat")
        mock_urlopen.assert_called_once()

    @patch("scraper.fangraphs.time.sleep")
    @patch("scraper.fangraphs.urlopen")
    def test_cloudflare_challenge_explains_block_without_retry(self, mock_urlopen, mock_sleep):
        headers = Message()
        headers["cf-mitigated"] = "challenge"
        failure = HTTPError(PROJECTION_URL, 403, "Forbidden", headers, None)
        mock_urlopen.side_effect = failure

        with self.assertRaisesRegex(RuntimeError, "FanGraphs.*machine access.*approved feed") as raised:
            fetch_projections("steamer", "bat")

        self.assertIs(raised.exception.__cause__, failure)
        mock_urlopen.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("scraper.fangraphs.time.sleep")
    @patch("scraper.fangraphs.urlopen")
    def test_ordinary_forbidden_preserves_http_error_without_retry(self, mock_urlopen, mock_sleep):
        failure = HTTPError(PROJECTION_URL, 403, "Forbidden", None, None)
        mock_urlopen.side_effect = failure

        with self.assertRaises(HTTPError) as raised:
            fetch_projections("steamer", "bat")

        self.assertIs(raised.exception, failure)
        mock_urlopen.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("scraper.fangraphs.time.sleep")
    @patch("scraper.fangraphs.urlopen")
    def test_transient_server_error_still_retries(self, mock_urlopen, mock_sleep):
        failure = HTTPError(PROJECTION_URL, 503, "Unavailable", None, None)
        mock_urlopen.side_effect = [failure, self._mock_response([])]

        self.assertEqual(fetch_projections("steamer", "bat"), [])

        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(2)

    @patch("scraper.fangraphs.urlopen")
    def test_fetch_builds_correct_url(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([])
        fetch_projections("steamerr", "pit")
        called_url = mock_urlopen.call_args[0][0].full_url
        self.assertIn("type=steamerr", called_url)
        self.assertIn("stats=pit", called_url)

    @patch("scraper.fangraphs.urlopen")
    def test_both_projection_requests_use_accepted_client_header(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([])
        fetch_all(delay=0, system="steamer")

        self.assertEqual(mock_urlopen.call_count, 2)
        for call, stats in zip(mock_urlopen.call_args_list, ("bat", "pit")):
            with self.subTest(stats=stats):
                request = call.args[0]
                self.assertEqual(request.get_header("User-agent"), "okhttp/4.12.0")
                self.assertEqual(
                    request.full_url,
                    "https://www.fangraphs.com/api/projections"
                    f"?type=steamer&stats={stats}&pos=all&team=0&players=0&lg=all",
                )

    @patch("scraper.fangraphs.urlopen")
    def test_fetch_all_returns_two_keys(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([])
        result = fetch_all(delay=0)
        self.assertEqual(set(result.keys()), {
            "steamer_hitters", "steamer_pitchers",
        })

    def test_projection_url_format(self):
        self.assertIn("fangraphs.com/api/projections", PROJECTION_URL)


if __name__ == "__main__":
    unittest.main()
