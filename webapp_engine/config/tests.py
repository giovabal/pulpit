import tempfile
from pathlib import Path

from django.test import TestCase

from webapp_engine.config import (
    CRAWL_DEFAULTS,
    STRUCTURAL_DEFAULTS,
    load_crawl_settings,
    load_structural_settings,
    paths as config_paths,
    read_pulpit_version,
    save_crawl_settings,
    save_structural_settings,
)


class _RedirectConfigPaths:
    """Redirect CRAWL_PATH / STRUCTURAL_PATH / CONFIG_DIR to a temp directory.

    Avoids touching the developer's real configuration/ on disk during tests.
    """

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig: dict = {}

    def __enter__(self):
        for attr in ("CONFIG_DIR", "CRAWL_PATH", "STRUCTURAL_PATH"):
            self._orig[attr] = getattr(config_paths, attr)
        config_paths.CONFIG_DIR = self.tmp
        config_paths.CRAWL_PATH = self.tmp / ".operations-crawl"
        config_paths.STRUCTURAL_PATH = self.tmp / ".operations-structural"
        # Reload modules that captured the path constants at import time.
        from webapp_engine.config import loader, writer

        loader.CRAWL_PATH = config_paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = config_paths.STRUCTURAL_PATH
        writer.CRAWL_PATH = config_paths.CRAWL_PATH
        writer.STRUCTURAL_PATH = config_paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = config_paths.CONFIG_DIR
        return self.tmp

    def __exit__(self, *exc):
        from webapp_engine.config import loader, writer

        for attr, value in self._orig.items():
            setattr(config_paths, attr, value)
        loader.CRAWL_PATH = config_paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = config_paths.STRUCTURAL_PATH
        writer.CRAWL_PATH = config_paths.CRAWL_PATH
        writer.STRUCTURAL_PATH = config_paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = config_paths.CONFIG_DIR


class HermeticLoadTests(TestCase):
    """Hermetic mode bypasses files entirely so tests never see local state."""

    def test_crawl_hermetic_returns_defaults(self) -> None:
        ns = load_crawl_settings(hermetic=True)
        self.assertEqual(ns.telegram.connection_retries, CRAWL_DEFAULTS["telegram"]["connection_retries"])
        self.assertEqual(ns.downloads.images, CRAWL_DEFAULTS["downloads"]["images"])
        self.assertEqual(ns.scope.channel_types, CRAWL_DEFAULTS["scope"]["channel_types"])

    def test_structural_hermetic_returns_defaults(self) -> None:
        ns = load_structural_settings(hermetic=True)
        self.assertEqual(ns.measures.selected, STRUCTURAL_DEFAULTS["measures"]["selected"])
        self.assertEqual(ns.robustness.enabled, STRUCTURAL_DEFAULTS["robustness"]["enabled"])


class MissingFileFallbackTests(TestCase):
    def test_load_returns_defaults_when_file_absent(self) -> None:
        with _RedirectConfigPaths():
            ns = load_crawl_settings(hermetic=False)
            self.assertEqual(ns.telegram.session_name, "anon")
            self.assertEqual(ns.downloads.images, False)


class RoundTripTests(TestCase):
    def test_save_then_load_crawl(self) -> None:
        with _RedirectConfigPaths() as tmp:
            save_crawl_settings(
                {
                    "telegram": {"connection_retries": 99, "session_name": "alt"},
                    "downloads": {"video": True},
                    "scope": {"channel_types": ["CHANNEL", "GROUP"]},
                }
            )
            self.assertTrue((tmp / ".operations-crawl").exists())
            ns = load_crawl_settings(hermetic=False)
            self.assertEqual(ns.telegram.connection_retries, 99)
            self.assertEqual(ns.telegram.session_name, "alt")
            self.assertEqual(ns.downloads.video, True)
            self.assertEqual(ns.downloads.images, False)
            self.assertEqual(ns.scope.channel_types, ["CHANNEL", "GROUP"])
            # Untouched defaults come through.
            self.assertEqual(ns.telegram.grace_time, 1)

    def test_save_then_load_structural(self) -> None:
        with _RedirectConfigPaths() as tmp:
            save_structural_settings(
                {
                    "outputs": {"graph": True, "html": True},
                    "measures": {"selected": ["PAGERANK", "BETWEENNESS"]},
                    "robustness": {"enabled": True, "strategies": ["pagerank"]},
                }
            )
            self.assertTrue((tmp / ".operations-structural").exists())
            ns = load_structural_settings(hermetic=False)
            self.assertEqual(ns.outputs.graph, True)
            self.assertEqual(ns.outputs.html, True)
            self.assertEqual(ns.outputs.xlsx, False)
            self.assertEqual(ns.measures.selected, ["PAGERANK", "BETWEENNESS"])
            self.assertEqual(ns.robustness.enabled, True)
            self.assertEqual(ns.robustness.strategies, ["pagerank"])
            self.assertEqual(ns.communities.strategies, ["ORGANIZATION"])


class VersionStampTests(TestCase):
    def test_pulpit_version_field_written_and_readable(self) -> None:
        with _RedirectConfigPaths() as tmp:
            save_crawl_settings({"downloads": {"images": True}})
            version = read_pulpit_version(tmp / ".operations-crawl")
            self.assertIsNotNone(version)
            self.assertNotEqual(version, "")


class CommentPreservationTests(TestCase):
    """tomlkit must keep user-added comments alive across writes — the make-or-break property."""

    def test_user_comment_survives_overwrite(self) -> None:
        with _RedirectConfigPaths() as tmp:
            save_crawl_settings({"telegram": {"connection_retries": 50}})
            content = (tmp / ".operations-crawl").read_text()
            # Inject a hand-written comment, then save again — the comment must survive.
            content = content.replace("[telegram]", "[telegram]\n# user note: do not bump this number")
            (tmp / ".operations-crawl").write_text(content)

            save_crawl_settings({"downloads": {"audio": True}})
            final = (tmp / ".operations-crawl").read_text()
            self.assertIn("user note: do not bump this number", final)
            self.assertIn("audio = true", final)
            self.assertIn("connection_retries = 50", final)


class MalformedTOMLFallbackTests(TestCase):
    def test_malformed_file_falls_back_to_defaults(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-crawl").write_text("this is = not valid toml [[[")
            ns = load_crawl_settings(hermetic=False)
            self.assertEqual(ns.telegram.session_name, "anon")
            self.assertEqual(ns.telegram.connection_retries, 10)
