"""Validation structurelle du catalogue international de sources."""
import json
import unittest
from pathlib import Path


class SourceCatalogTests(unittest.TestCase):
    def test_twenty_named_feeds_have_country_region_and_language(self):
        path = Path(__file__).resolve().parents[1] / "sources.json"
        sources = json.loads(path.read_text(encoding="utf-8"))["sources"]
        sites = [source for source in sources if source.get("source_type") != "market_search"]
        markets = [source for source in sources if source.get("source_type") == "market_search"]
        self.assertEqual(len(sites), 20)
        self.assertEqual(len(markets), 7)
        self.assertEqual(len({source["name"] for source in sources}), 27)
        self.assertTrue(all(source.get("country") for source in sources))
        self.assertTrue(all(source.get("region") for source in sources))
        self.assertTrue(all(source.get("language") for source in sources))
        self.assertGreaterEqual(len({source["country"] for source in sites}), 6)
        self.assertEqual(len({source["market_country"] for source in markets}), 7)
        self.assertTrue(any("official" in source.get("category", "") for source in sources))


if __name__ == "__main__":
    unittest.main()
