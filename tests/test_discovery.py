import json
import unittest

import httpx

from parser.discovery import BraveSearchProvider, DiscoveryService


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

    async def test_discovery_does_not_fetch_next_page_until_needed(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            payload = {
                "query": {"more_results_available": True},
                "web": {
                    "results": [
                        {
                            "title": f"Clinic {index}",
                            "url": f"https://clinic-{index}.example/",
                        }
                        for index in range(20)
                    ]
                },
            }
            return httpx.Response(200, content=json.dumps(payload).encode())

        provider = BraveSearchProvider(
            api_key="secret-key",
            timeout=5,
            user_agent="test-agent",
            transport=httpx.MockTransport(handler),
        )
        discovery = DiscoveryService(provider, set())
        collected = []
        async for result in discovery.iter_discover("клиники", 200):
            collected.append(result)
            if len(collected) == 5:
                break

        self.assertEqual(len(collected), 5)
        self.assertEqual(request_count, 1)


if __name__ == "__main__":
    unittest.main()
