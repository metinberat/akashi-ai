import asyncio
import unittest
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import HTTPException

from app.api.image import _comfy_request, extract_image_urls, validate_image_location


class ImageUrlTests(unittest.TestCase):
    def test_output_is_relative_to_the_fastapi_backend(self) -> None:
        history = {
            "outputs": {
                "9": {
                    "images": [
                        {
                            "filename": "Akashi image.png",
                            "subfolder": "results",
                            "type": "output",
                        }
                    ]
                }
            }
        }

        urls = extract_image_urls(history)

        self.assertEqual(len(urls), 1)
        parsed = urlsplit(urls[0])
        self.assertEqual(parsed.path, "/image/view")
        self.assertEqual(parsed.scheme, "")
        self.assertEqual(parsed.netloc, "")
        self.assertEqual(parse_qs(parsed.query)["filename"], ["Akashi image.png"])

    def test_comfy_view_paths_reject_traversal(self) -> None:
        validate_image_location("result.png", "safe/subfolder")
        for filename, subfolder in (
            ("../secret.png", ""),
            ("secret.png", "../../outside"),
            ("folder/secret.png", ""),
        ):
            with self.assertRaises(ValueError):
                validate_image_location(filename, subfolder)

    def test_untrusted_comfy_output_is_not_returned(self) -> None:
        history = {"outputs": {"9": {"images": [
            {"filename": "../private.png", "subfolder": "", "type": "output"},
            {"filename": "result.png", "subfolder": "safe", "type": "unknown"},
        ]}}}
        self.assertEqual(extract_image_urls(history), [])

    def test_comfy_connection_failure_is_a_precise_503(self) -> None:
        class OfflineClient:
            async def request(self, method, url, **kwargs):
                raise httpx.ConnectError("offline", request=httpx.Request(method, url))

        with self.assertRaises(HTTPException) as caught:
            asyncio.run(_comfy_request(OfflineClient(), "GET", "/system_stats"))  # type: ignore[arg-type]
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
