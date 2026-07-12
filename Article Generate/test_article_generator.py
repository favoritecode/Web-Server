import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("routes.py")
spec = importlib.util.spec_from_file_location("article_routes", MODULE_PATH)
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)

WINDOWS_SHORTCUT_TITLE = "windows 11 most usefull \u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f, \u098f\u0997\u09c1\u09b2\u09cb \u099c\u09be\u09a8\u09b2\u09c7 \u0986\u09aa\u09a8\u09bf \u099c\u09bf\u09a8\u09bf\u09df\u09be\u09b8\u0964"

TEST_TITLES = [
    "Best skincare routine for oily skin",
    "How to grow a small online business",
    "Top budget smartphones for students",
    "Healthy breakfast ideas for busy people",
    "Facebook page growth tips for beginners",
    "AI tools for content creators",
    "How to choose the right laptop",
    "Simple home workout plan",
    "Travel guide for Cox's Bazar",
    "YouTube video description writing tips",
]


class ArticleGeneratorTests(unittest.TestCase):
    def setUp(self):
        self._original_secret_value = routes._secret_value
        routes._secret_value = lambda name, default="": "" if name in {"GEMINI_API_KEY", "GOOGLE_AI_API_KEY", "NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CF_ACCOUNT_ID", "CF_API_TOKEN", "OPENAI_API_KEY"} else default

    def tearDown(self):
        routes._secret_value = self._original_secret_value

    def make_package(self, title):
        settings = routes._settings_from_payload({"title": title})
        package = routes.generate_article_package(settings)
        self.assertNotIn("error", package, package.get("validation"))
        return package

    def test_mandatory_title_quality(self):
        title = TEST_TITLES[0]
        package = self.make_package(title)
        article = package["article"]
        validation = package["validation"]
        self.assertTrue(validation["isValid"], validation)
        self.assertTrue(article.startswith(f"# {title}"))
        self.assertEqual(validation["bannedPhrasesFound"], [])
        self.assertLessEqual(validation["titleRepetitionCount"], 3)
        self.assertGreaterEqual(validation["wordCount"], 200)
        self.assertLessEqual(validation["wordCount"], 500)
        self.assertNotIn("FixedBrandExample", article)
        for unsafe in routes.UNSAFE_CLAIMS:
            self.assertNotIn(unsafe, article)

    def test_all_generic_titles_pass_validation(self):
        for title in TEST_TITLES:
            with self.subTest(title=title):
                package = self.make_package(title)
                validation = package["validation"]
                self.assertTrue(validation["isValid"], validation)
                self.assertGreaterEqual(validation["wordCount"], 200)
                self.assertLessEqual(validation["wordCount"], 500)
                self.assertLessEqual(validation["titleRepetitionCount"], 3)
                self.assertTrue(package["article"].startswith(f"# {title}"))
                self.assertTrue(package["tags"])
                self.assertLessEqual(routes._word_count(" ".join(package["tags"])), 200)
                self.assertTrue(package["hashtags"])


    def test_tags_are_seo_keyword_phrases(self):
        package = self.make_package("Best skincare routine for oily skin")
        tags = [tag.lower() for tag in package["tags"]]
        joined = ", ".join(tags)
        self.assertIn("best skincare routine", joined)
        self.assertIn("skincare routine for oily skin", joined)
        self.assertIn("oily skin care tips", joined)
        self.assertLessEqual(routes._word_count(" ".join(package["tags"])), 200)
        self.assertTrue(all(routes._word_count(tag) <= 7 for tag in package["tags"]))


    def test_windows_shortcut_title_gets_practical_content_and_seo_tags(self):
        package = self.make_package(WINDOWS_SHORTCUT_TITLE)
        article = package["article"]
        joined_tags = ", ".join(package["tags"])
        self.assertIn("Win + E", article)
        self.assertIn("Win + Shift + S", article)
        self.assertIn("Ctrl + Shift + Esc", article)
        self.assertIn("Windows 11 shortcuts", joined_tags)
        self.assertIn("Windows 11 keyboard shortcuts", joined_tags)
        self.assertIn("Windows 11 shortcut keys", joined_tags)
        self.assertIn("Windows 11 tips and tricks", joined_tags)
        self.assertNotIn("????", article)
        self.assertNotIn("????", joined_tags)
        self.assertLessEqual(routes._word_count(" ".join(package["tags"])), 200)

    def test_validator_catches_banned_generic_copy(self):
        bad = "This draft uses trusted source, better engagement and long-term result as generic filler."
        result = routes.validate_article(bad, TEST_TITLES[0], min_words=10)
        self.assertFalse(result["isValid"])
        self.assertTrue(result["bannedPhrasesFound"])

    def test_metadata_is_returned(self):
        package = self.make_package(TEST_TITLES[1])
        self.assertTrue(package["metaTitle"])
        self.assertTrue(package["metaDescription"])
        self.assertTrue(package["slug"])
        self.assertLessEqual(len(package["metaDescription"]), 160)


if __name__ == "__main__":
    unittest.main()
