import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock wand before importing telegram_manager
sys.modules['wand'] = MagicMock()
sys.modules['wand.image'] = MagicMock()
sys.modules['wand.resource'] = MagicMock()

from modules.telegram_manager import (
    TelegramManager,
    imagemagick_limits,
    use_bundled_imagemagick_policy,
)


class TestGetMessageMarkup(unittest.TestCase):
    """
    Tests for TelegramManager.get_message_markup()

    Returns form field values now, not a pre-encoded query fragment. Nothing is
    quoted by hand: requests encodes the values when posting them.
    """

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        """Set up a TelegramManager instance with mocked dependencies."""
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    def test_special_characters_are_left_unencoded(self):
        """The caption is a value, so &, < and > travel through verbatim."""
        image = {
            "title": "Test & Title <with> special chars",
            "creator": "Artist & Co.",
        }

        fields = self.manager.get_message_markup(image)

        self.assertIn("Test & Title <with> special chars", fields['caption'])
        self.assertIn("Artist & Co.", fields['caption'])
        self.assertNotIn("%26", fields['caption'], "values must not be pre-encoded")

    def test_simple_caption(self):
        fields = self.manager.get_message_markup({"title": "Simple Title", "creator": "SimpleArtist"})
        self.assertIn("Simple Title", fields['caption'])
        self.assertIn("SimpleArtist", fields['caption'])

    def test_handles_empty_caption(self):
        self.assertEqual("No info.", self.manager.get_message_markup({})['caption'])

    def test_truncates_long_caption(self):
        """Telegram rejects captions over 1024 characters."""
        image = {"title": "A" * 500, "creator": "B" * 500, "character": "C" * 500}

        caption = self.manager.get_message_markup(image)['caption']

        self.assertLessEqual(len(caption), 1024)
        self.assertTrue(caption.endswith("..."))

    def test_reply_markup_is_a_json_string(self):
        """Telegram expects reply_markup as JSON text, not a nested object."""
        self.manager.build_caption_buttons = MagicMock(return_value={'inline_keyboard': [[{'text': 'e621', 'url': 'https://e621.net/posts/1'}]]})

        fields = self.manager.get_message_markup({"sauce": "https://e621.net/posts/1"})

        self.assertIsInstance(fields['reply_markup'], str)
        self.assertEqual({'inline_keyboard': [[{'text': 'e621', 'url': 'https://e621.net/posts/1'}]]},
                         json.loads(fields['reply_markup']))

    def test_no_reply_markup_without_sauce(self):
        self.assertNotIn('reply_markup', self.manager.get_message_markup({"title": "T"}))

    def test_returns_only_known_fields(self):
        self.manager.build_caption_buttons = MagicMock(return_value={'inline_keyboard': [[]]})
        fields = self.manager.get_message_markup({"sauce": "x", "title": "T"})
        self.assertEqual({'caption', 'reply_markup'}, set(fields))


class TestConcatenateSauce(unittest.TestCase):
    """
    Tests for TelegramManager.concatenate_sauce() and is_source_page()

    The filter previously required a URL to start with "https://www." or the e621
    posts path, which tested the wrong property. It dropped source pages that do
    not use a www subdomain and kept direct file links that do.
    """

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    # --- pages that must be kept ---

    def test_keeps_pages_without_a_www_subdomain(self):
        """The main regression: these were all silently dropped."""
        for url in ("https://furaffinity.net/view/12345/",
                    "https://x.com/someone/status/123",
                    "https://inkbunny.net/s/1234567",
                    "https://e621.net/posts/456"):
            with self.subTest(url=url):
                self.assertTrue(self.manager.is_source_page(url))

    def test_keeps_pages_with_a_www_subdomain(self):
        self.assertTrue(self.manager.is_source_page("https://www.furaffinity.net/view/12345/"))

    def test_keeps_http_pages(self):
        """Old source URLs recorded over http are still useful links."""
        self.assertTrue(self.manager.is_source_page("http://www.oldsite.com/view/1"))

    def test_keeps_a_page_whose_path_merely_contains_an_extension(self):
        self.assertTrue(self.manager.is_source_page("https://example.com/view/image.jpg/about"))

    # --- direct file links that must be dropped ---

    def test_drops_direct_media_links(self):
        for url in ("https://static1.e621.net/data/ab/cd/abcd.jpg",
                    "https://i.redd.it/abc123.png",
                    "https://cdn.example.com/a.webm",
                    "https://cdn.example.com/a.mp4"):
            with self.subTest(url=url):
                self.assertFalse(self.manager.is_source_page(url))

    def test_drops_a_direct_link_that_has_a_www_subdomain(self):
        """Previously kept, because the filter only looked at the prefix."""
        self.assertFalse(self.manager.is_source_page("https://www.somecdn.com/files/image.jpg"))

    def test_extension_match_is_case_insensitive(self):
        self.assertFalse(self.manager.is_source_page("https://cdn.example.com/A.JPG"))

    # --- malformed input ---

    def test_rejects_unusable_values(self):
        for value in ("", "not a url", "ftp://example.com/a", "/relative/path", None, 123):
            with self.subTest(value=value):
                self.assertFalse(self.manager.is_source_page(value))

    # --- joining ---

    def test_returns_comma_separated_urls(self):
        urls = ["https://www.example.com/page1", "https://www.example.com/page2"]
        self.assertEqual("https://www.example.com/page1, https://www.example.com/page2",
                         self.manager.concatenate_sauce(urls))

    def test_empty_list_returns_empty_string(self):
        self.assertEqual("", self.manager.concatenate_sauce([]))

    def test_none_returns_empty_string(self):
        self.assertEqual("", self.manager.concatenate_sauce(None))

    def test_all_filtered_returns_empty_string(self):
        self.assertEqual("", self.manager.concatenate_sauce(["https://static1.e621.net/data/image.jpg"]))

    def test_no_trailing_comma(self):
        result = self.manager.concatenate_sauce(["https://www.example.com/page1"])
        self.assertFalse(result.endswith(","))

    # --- deduplication ---

    def test_collapses_www_and_bare_forms_of_one_page(self):
        """Hydrus commonly records both, which would otherwise make two buttons."""
        result = self.manager.concatenate_sauce([
            "https://www.furaffinity.net/view/12345/",
            "https://furaffinity.net/view/12345/",
        ])
        self.assertEqual("https://www.furaffinity.net/view/12345/", result)

    def test_collapses_http_and_https_forms(self):
        result = self.manager.concatenate_sauce([
            "https://example.com/view/1", "http://example.com/view/1",
        ])
        self.assertEqual("https://example.com/view/1", result)

    def test_collapses_a_trailing_slash_difference(self):
        result = self.manager.concatenate_sauce([
            "https://example.com/view/1", "https://example.com/view/1/",
        ])
        self.assertEqual("https://example.com/view/1", result)

    def test_keeps_genuinely_different_pages(self):
        result = self.manager.concatenate_sauce([
            "https://example.com/view/1", "https://example.com/view/2",
        ])
        self.assertEqual(2, len(result.split(", ")))

    def test_query_strings_distinguish_pages(self):
        result = self.manager.concatenate_sauce([
            "https://example.com/view?id=1", "https://example.com/view?id=2",
        ])
        self.assertEqual(2, len(result.split(", ")))

    def test_preserves_input_order(self):
        result = self.manager.concatenate_sauce([
            "https://b.example.com/2", "https://a.example.com/1",
        ])
        self.assertEqual("https://b.example.com/2, https://a.example.com/1", result)


class TestEscapeHtml(unittest.TestCase):
    """
    Tests for TelegramManager.escape_html()

    Captions are sent with parse_mode=html, so characters that would be read as
    markup must be escaped. The previous implementation substituted lookalike
    characters instead, which rendered fine but silently changed the data.
    """

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    def test_ampersand_is_escaped_not_replaced(self):
        """The reported symptom: "Tom & Jerry" used to post as "Tom + Jerry"."""
        self.assertEqual("Tom &amp; Jerry", self.manager.escape_html("Tom & Jerry"))

    def test_angle_brackets_are_escaped(self):
        self.assertEqual("&lt;tag&gt;", self.manager.escape_html("<tag>"))

    def test_data_survives_a_round_trip(self):
        """Escaping must be reversible; the old substitution was not."""
        import html as html_module
        for original in ("Tom & Jerry", "a < b > c", "AT&T", "5 > 3 & 2 < 4", "plain"):
            with self.subTest(text=original):
                self.assertEqual(original, html_module.unescape(self.manager.escape_html(original)))

    def test_lookalike_characters_are_not_used(self):
        result = self.manager.escape_html("a & b < c > d")
        self.assertNotIn("+", result)
        self.assertNotIn("\u227a", result)
        self.assertNotIn("\u227b", result)

    def test_plain_text_is_unchanged(self):
        self.assertEqual("plain text", self.manager.escape_html("plain text"))

    def test_quotes_are_left_alone(self):
        """This text goes between tags, never into an attribute."""
        self.assertEqual("it's a \"quote\"", self.manager.escape_html('it\'s a "quote"'))

    def test_none_passes_through(self):
        self.assertIsNone(self.manager.escape_html(None))

    def test_already_escaped_text_is_escaped_again(self):
        """Documents that escaping is not idempotent, so it must be applied once."""
        self.assertEqual("&amp;amp;", self.manager.escape_html("&amp;"))


class TestBuildTelegramApiUrl(unittest.TestCase):
    """Tests for TelegramManager.build_telegram_api_url()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.token = "123:ABC"

    def test_basic_api_url(self):
        url = self.manager.build_telegram_api_url("sendMessage", "?chat_id=123")
        self.assertEqual("https://api.telegram.org/bot123:ABC/sendMessage?chat_id=123", url)

    def test_strips_extra_question_mark(self):
        """Payload with leading ? should not produce double ??."""
        url = self.manager.build_telegram_api_url("sendMessage", "?chat_id=123")
        self.assertNotIn("??", url)

    def test_file_url(self):
        url = self.manager.build_telegram_api_url("", "?file_path=photos/file.jpg", is_file=True)
        self.assertIn("file/bot123:ABC", url)
        self.assertNotIn("/sendMessage", url)

    def test_no_payload(self):
        url = self.manager.build_telegram_api_url("getMe", "")
        self.assertEqual("https://api.telegram.org/bot123:ABC/getMe", url)


class TestRedactToken(unittest.TestCase):
    """Tests for TelegramManager._redact_token()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.token = "123:SECRET_TOKEN"

    def test_redacts_token(self):
        text = "Error at https://api.telegram.org/bot123:SECRET_TOKEN/sendMessage"
        result = self.manager._redact_token(text)
        self.assertNotIn("123:SECRET_TOKEN", result)
        self.assertIn("[REDACTED]", result)

    def test_no_token_unchanged(self):
        text = "No token here"
        result = self.manager._redact_token(text)
        self.assertEqual("No token here", result)


class TestBuildCaptionButtons(unittest.TestCase):
    """Tests for TelegramManager.build_caption_buttons()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    def test_none_caption_returns_none(self):
        result = self.manager.build_caption_buttons(None)
        self.assertIsNone(result)

    def test_e621_url_gets_label(self):
        caption = "https://e621.net/posts/123"
        result = self.manager.build_caption_buttons(caption)
        self.assertIsNotNone(result)
        buttons = result['inline_keyboard']
        self.assertEqual(1, len(buttons))
        self.assertEqual('e621', buttons[0][0]['text'])

    def test_reddit_url_with_subreddit(self):
        caption = "https://www.reddit.com/r/aww/comments/abc123"
        result = self.manager.build_caption_buttons(caption)
        buttons = result['inline_keyboard']
        self.assertIn('Reddit', buttons[0][0]['text'])
        self.assertIn('r/aww', buttons[0][0]['text'])

    def test_multiple_urls_in_two_columns(self):
        """Two URLs should be in the same row (two-column layout)."""
        caption = "https://e621.net/posts/1, https://e621.net/posts/2"
        result = self.manager.build_caption_buttons(caption)
        buttons = result['inline_keyboard']
        # Two URLs should be in the same row
        self.assertEqual(1, len(buttons))
        self.assertEqual(2, len(buttons[0]))

    def test_button_layout_wraps_at_two_per_row(self):
        """
        Pins the column toggle across several rows.

        The toggle was written as `url_column == 0 and 1 or 0`, which is correct
        but obscures the intent, and the and/or form silently returns the wrong
        branch whenever the middle value is falsy.
        """
        expected = {1: [1], 2: [2], 3: [2, 1], 4: [2, 2], 5: [2, 2, 1], 6: [2, 2, 2]}
        for count, shape in expected.items():
            with self.subTest(urls=count):
                caption = ", ".join(f"https://e621.net/posts/{i}" for i in range(count))
                rows = self.manager.build_caption_buttons(caption)['inline_keyboard']
                self.assertEqual(shape, [len(row) for row in rows])

    def test_every_url_gets_exactly_one_button(self):
        """No link may be dropped or duplicated by the row bookkeeping."""
        urls = [f"https://e621.net/posts/{i}" for i in range(7)]
        rows = self.manager.build_caption_buttons(", ".join(urls))['inline_keyboard']
        emitted = [button['url'] for row in rows for button in row]
        self.assertEqual(urls, emitted)

    def test_single_url_makes_one_row(self):
        rows = self.manager.build_caption_buttons("https://e621.net/posts/1")['inline_keyboard']
        self.assertEqual([1], [len(row) for row in rows])

    def test_no_http_links_returns_empty_keyboard(self):
        caption = "just some text without urls"
        result = self.manager.build_caption_buttons(caption)
        self.assertEqual({'inline_keyboard': []}, result)


if __name__ == "__main__":
    unittest.main()


class TestImagemagickLimits(unittest.TestCase):
    """
    Tests for imagemagick_limits().

    ImageMagick decodes files downloaded from the internet. Its stock limits are
    effectively unbounded (time and disk are the 64-bit maximum), which makes
    decompression bombs cheap, so every limit the bot computes must be finite.
    """

    MAXINT64 = 2 ** 63 - 1

    def test_memory_is_converted_from_mb_to_bytes(self):
        self.assertEqual(256 * 1024 * 1024, imagemagick_limits(256, 60, 50000)['memory'])

    def test_spill_limits_are_derived_from_memory(self):
        v = imagemagick_limits(100, 60, 50000)
        self.assertEqual(v['memory'] * 2, v['map'])
        self.assertEqual(v['memory'] * 4, v['disk'])
        self.assertEqual(v['memory'], v['area'])

    def test_time_and_dimensions_pass_through(self):
        v = imagemagick_limits(256, 45, 12345)
        self.assertEqual(45, v['time'])
        self.assertEqual(12345, v['width'])
        self.assertEqual(12345, v['height'])

    def test_single_threaded(self):
        self.assertEqual(1, imagemagick_limits(256, 60, 50000)['thread'])

    def test_every_limit_is_finite(self):
        """The defaults this replaces include 64-bit-max time and disk limits."""
        for key, value in imagemagick_limits(256, 60, 50000).items():
            with self.subTest(limit=key):
                self.assertLess(value, self.MAXINT64, f"{key} must be bounded")
                self.assertGreater(value, 0, f"{key} must be positive")

    def test_covers_the_limits_that_ship_unbounded(self):
        keys = imagemagick_limits(256, 60, 50000).keys()
        for key in ('time', 'disk', 'memory', 'map', 'area', 'width', 'height'):
            self.assertIn(key, keys)


class TestApplyImagemagickLimits(unittest.TestCase):
    """Tests for TelegramManager.apply_imagemagick_limits()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.imagemagick_memory_limit_mb = 256
        self.manager.config.imagemagick_time_limit_seconds = 60
        self.manager.config.imagemagick_max_source_dimension = 50000

    def test_applies_every_limit(self):
        fake = {}
        with patch('modules.telegram_manager.limits', fake):
            self.manager.apply_imagemagick_limits()

        self.assertEqual(imagemagick_limits(256, 60, 50000), fake)

    def test_uses_configured_values(self):
        self.manager.config.imagemagick_memory_limit_mb = 64
        self.manager.config.imagemagick_time_limit_seconds = 5
        self.manager.config.imagemagick_max_source_dimension = 999
        fake = {}
        with patch('modules.telegram_manager.limits', fake):
            self.manager.apply_imagemagick_limits()

        self.assertEqual(64 * 1024 * 1024, fake['memory'])
        self.assertEqual(5, fake['time'])
        self.assertEqual(999, fake['width'])

    def test_unsupported_limit_is_logged_not_raised(self):
        """An older ImageMagick rejecting one key must not stop the bot starting."""
        class Picky(dict):
            def __setitem__(self, key, value):
                if key == 'area':
                    raise ValueError("unsupported limit")
                super().__setitem__(key, value)

        fake = Picky()
        with patch('modules.telegram_manager.limits', fake):
            self.manager.apply_imagemagick_limits()

        self.assertNotIn('area', fake)
        self.assertIn('memory', fake, "other limits must still be applied")
        self.assertTrue(self.manager.logger.warning.called)


class TestUseBundledImagemagickPolicy(unittest.TestCase):
    """
    Tests for use_bundled_imagemagick_policy().

    The bundled policy is what denies ImageMagick's scripting and network coders.
    Without it ImageMagick will genuinely issue an outbound request for an image
    that asks it to, so the variable must actually get set.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.policy_dir = pathlib.Path(self.tmp)

    def _with_policy(self):
        (self.policy_dir / "policy.xml").write_text("<policymap/>")
        return self.policy_dir

    def test_sets_the_variable_when_policy_exists(self):
        env = {}
        self.assertTrue(use_bundled_imagemagick_policy(self._with_policy(), env))
        self.assertEqual(str(self.policy_dir), env["MAGICK_CONFIGURE_PATH"])

    def test_does_not_override_an_operator_setting(self):
        """Someone who pointed ImageMagick somewhere deliberately keeps that choice."""
        env = {"MAGICK_CONFIGURE_PATH": "/operator/choice"}
        self.assertFalse(use_bundled_imagemagick_policy(self._with_policy(), env))
        self.assertEqual("/operator/choice", env["MAGICK_CONFIGURE_PATH"])

    def test_no_op_when_policy_file_is_missing(self):
        """A missing policy must not point ImageMagick at an empty directory."""
        env = {}
        self.assertFalse(use_bundled_imagemagick_policy(self.policy_dir, env))
        self.assertNotIn("MAGICK_CONFIGURE_PATH", env)

    def test_no_op_when_directory_is_missing(self):
        env = {}
        self.assertFalse(use_bundled_imagemagick_policy(self.policy_dir / "nope", env))
        self.assertNotIn("MAGICK_CONFIGURE_PATH", env)


class TestBundledPolicyFile(unittest.TestCase):
    """The shipped policy.xml must stay parseable and keep denying the risky coders."""

    @classmethod
    def setUpClass(cls):
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        cls.path = repo_root / "config" / "magick" / "policy.xml"
        cls.root = ET.parse(cls.path).getroot()

    def test_policy_ships_where_the_loader_expects_it(self):
        from modules.telegram_manager import POLICY_DIR
        self.assertEqual(POLICY_DIR / "policy.xml", self.path)

    def test_is_valid_xml_without_the_broken_doctype(self):
        """ImageMagick's stock DTD types attributes as NCName, which is not legal DTD."""
        self.assertNotIn("<!DOCTYPE", self.path.read_text())

    def test_denies_the_coders_with_rce_and_ssrf_history(self):
        denied = {p.get("pattern") for p in self.root.findall("policy")
                  if p.get("domain") == "coder" and p.get("rights") == "none"}
        for coder in ("MSL", "MVG", "URL", "HTTPS", "HTTP", "FTP", "EPHEMERAL", "PS", "PDF"):
            with self.subTest(coder=coder):
                self.assertIn(coder, denied)

    def test_denies_all_delegates_and_indirect_reads(self):
        rules = {(p.get("domain"), p.get("pattern")): p.get("rights")
                 for p in self.root.findall("policy")}
        self.assertEqual("none", rules.get(("delegate", "*")))
        self.assertEqual("none", rules.get(("path", "@*")))


class TestTelegramManagerRequiresToken(unittest.TestCase):
    """
    A missing token must fail loudly at construction.

    Returning from __init__ left self.token undefined, so the failure surfaced
    later as an AttributeError from whichever method ran first. _redact_token was
    the worst case: it is called from the handler for other failures, so a missing
    token masked whatever error was actually being reported.
    """

    def _config(self, token):
        config = MagicMock()
        config.config_data = MagicMock()
        config.config_data.telegram_access_token = token
        return config

    def test_empty_token_raises(self):
        with self.assertRaises(ValueError):
            TelegramManager(self._config(''))

    def test_none_token_raises(self):
        with self.assertRaises(ValueError):
            TelegramManager(self._config(None))

    def test_no_half_built_object_is_returned(self):
        """The object must not exist at all rather than exist without a token."""
        try:
            manager = TelegramManager(self._config(''))
        except ValueError:
            return
        self.fail(f"construction should have failed, got {manager!r}")
