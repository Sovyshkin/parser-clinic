import json
import unittest

import httpx

from parser.discovery import BraveSearchProvider


class BraveSearchProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_response_and_page_based_offset(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            offset = int(request.url.params["offset"])
            start = offset * 20
            count = int(request.url.params["count"])
            results = [
                {
                    "title": f"Clinic {index}",
                    "url": f"https://clinic-{index}.example/",
                }
                for index in range(start, start + count)
            ]
            payload = {
                "query": {"more_results_available": offset == 0},
                "web": {"results": results},
            }
            return httpx.Response(200, content=json.dumps(payload).encode())

        provider = BraveSearchProvider(
            api_key="secret-key",
            timeout=5,
            user_agent="test-agent",
            transport=httpx.MockTransport(handler),
        )
        results = await provider.search("стоматологии Москва", 25)

        self.assertEqual(len(results), 25)
        self.assertEqual([request.url.params["offset"] for request in requests], ["0", "1"])
        self.assertEqual(requests[0].headers["x-subscription-token"], "secret-key")
        self.assertEqual(requests[0].url.params["count"], "20")
        self.assertEqual(requests[1].url.params["count"], "5")


if __name__ == "__main__":
    unittest.main()

