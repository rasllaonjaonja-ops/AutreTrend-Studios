"""Tests de distinction entre lien officiel candidat et preuve factuelle."""
import unittest

from scripts.verify_sources import is_official, is_official_candidate


class OfficialLinkCandidateTests(unittest.TestCase):
    def test_viz_product_page_is_not_an_official_announcement_candidate(self):
        url = "https://www.viz.com/manga-books/manga/jojo-s-bizarre-adventure-part-7-steel-ball-run-volume-1/product/8330"
        self.assertTrue(is_official(url, "www.animenewsnetwork.com"))
        self.assertFalse(is_official_candidate(url, "www.animenewsnetwork.com"))

    def test_first_party_news_path_can_be_kept_as_candidate(self):
        url = "https://www.viz.com/news/steel-ball-run-anime-special-video"
        self.assertTrue(is_official_candidate(url, "www.animenewsnetwork.com"))

    def test_unlisted_media_domain_is_never_an_official_candidate(self):
        url = "https://www.animenewsnetwork.com/news/2026/example"
        self.assertFalse(is_official_candidate(url, "www.crunchyroll.com"))

    def test_same_publisher_link_is_not_external_official_evidence(self):
        url = "https://www.animenewsnetwork.com/news/2026/example"
        self.assertFalse(is_official_candidate(url, "www.animenewsnetwork.com"))


if __name__ == "__main__":
    unittest.main()
