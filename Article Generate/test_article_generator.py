import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("routes.py")
spec = importlib.util.spec_from_file_location("article_routes", MODULE_PATH)
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)

TEST_TITLES = [
    "বইয়ের ভেতর শিক্ষক থাকলে, লেখাপড়ায় আর প্রতিবন্ধকতা কিসের?",
    "QR কোড স্ক্যান করলেই শিক্ষক হাজির",
    "বইয়ের সাথে ২৪ ঘণ্টা শিক্ষক ফ্রি",
    "সমাধান না বুঝলে QR কোড স্ক্যান কর",
    "ইজি সিরিজে পড়াশোনা হবে বুঝে বুঝে",
    "অভিভাবকের দুশ্চিন্তা কমাবে বইয়ের ভিডিও শিক্ষক",
    "কোচিংয়ের অতিরিক্ত খরচ কমাতে পারে ইজি সিরিজ",
    "কঠিন অঙ্ক এখন ভিডিওতে ধাপে ধাপে",
    "বই খুললেই সমাধান, স্ক্যান করলেই শিক্ষক",
    "স্বশিক্ষায় QR কোডভিত্তিক বইয়ের ভূমিকা",
]


class ArticleGeneratorTests(unittest.TestCase):
    def setUp(self):
        self._original_secret_value = routes._secret_value
        routes._secret_value = lambda name, default="": "" if name in {"DEEPSEEK_API_KEY", "DEEPSEEK_WORKER_API_KEY", "OPENAI_API_KEY"} else default

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
        self.assertEqual(validation["bannedPhrasesFound"], [])
        self.assertLessEqual(validation["titleRepetitionCount"], 3)
        self.assertIn("QR", article)
        self.assertIn("ভিডিও শিক্ষক", article)
        self.assertRegex(article, r"কঠিন|সমাধান|ধাপে ধাপে")
        self.assertRegex(article, r"বারবার|replay|pause|পুনরায়")
        self.assertRegex(article, r"শিক্ষার্থী|অভিভাবক")
        for unsafe in routes.UNSAFE_CLAIMS:
            self.assertNotIn(unsafe, article)

    def test_all_required_titles_pass_validation(self):
        for title in TEST_TITLES:
            with self.subTest(title=title):
                package = self.make_package(title)
                validation = package["validation"]
                self.assertTrue(validation["isValid"], validation)
                self.assertGreaterEqual(validation["wordCount"], 500)
                self.assertLessEqual(validation["titleRepetitionCount"], 3)
                self.assertIn("QR", package["article"])
                self.assertIn("ভিডিও শিক্ষক", package["article"])

    def test_validator_catches_banned_generic_copy(self):
        bad = "বিষয়টি সম্পর্কে পরিষ্কার ধারণা থাকলে সিদ্ধান্ত নেওয়া, পরিকল্পনা করা এবং বাস্তবে ভালো ফল পাওয়া সহজ হয়। trusted source অনুসরণ করলে better engagement পাওয়া যায়।"
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