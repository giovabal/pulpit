import tempfile
from pathlib import Path

from django.test import TestCase

from webapp_engine.config import (
    CRAWL_DEFAULTS,
    STRUCTURAL_DEFAULTS,
    list_defaults,
    load_crawl_settings,
    load_payload_by_id,
    load_structural_settings,
    paths as config_paths,
    read_pulpit_version,
    save_named,
    write_baseline,
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

        loader.CONFIG_DIR = config_paths.CONFIG_DIR
        loader.CRAWL_PATH = config_paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = config_paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = config_paths.CONFIG_DIR
        return self.tmp

    def __exit__(self, *exc):
        from webapp_engine.config import loader, writer

        for attr, value in self._orig.items():
            setattr(config_paths, attr, value)
        loader.CONFIG_DIR = config_paths.CONFIG_DIR
        loader.CRAWL_PATH = config_paths.CRAWL_PATH
        loader.STRUCTURAL_PATH = config_paths.STRUCTURAL_PATH
        writer.CONFIG_DIR = config_paths.CONFIG_DIR


class HermeticLoadTests(TestCase):
    """Hermetic mode bypasses files entirely so tests never see local state."""

    def test_crawl_hermetic_returns_defaults(self) -> None:
        ns = load_crawl_settings(hermetic=True)
        # `telegram.*` is intentionally absent — Telegram client tuning is now
        # owned by `.env`, not by `.operations-crawl`.
        self.assertNotIn("telegram", CRAWL_DEFAULTS)
        self.assertEqual(ns.downloads.images, CRAWL_DEFAULTS["downloads"]["images"])
        self.assertEqual(ns.scope.channel_types, CRAWL_DEFAULTS["scope"]["channel_types"])

    def test_structural_hermetic_returns_defaults(self) -> None:
        ns = load_structural_settings(hermetic=True)
        self.assertEqual(ns.measures.selected, STRUCTURAL_DEFAULTS["measures"]["selected"])
        # `robustness.enabled` is intentionally absent from STRUCTURAL_DEFAULTS;
        # SA_ROBUSTNESS is derived from bool(strategies) in settings.py.
        self.assertNotIn("enabled", STRUCTURAL_DEFAULTS["robustness"])
        self.assertEqual(ns.robustness.strategies, STRUCTURAL_DEFAULTS["robustness"]["strategies"])


class MissingFileFallbackTests(TestCase):
    def test_load_returns_defaults_when_file_absent(self) -> None:
        with _RedirectConfigPaths():
            ns = load_crawl_settings(hermetic=False)
            self.assertEqual(ns.downloads.images, False)
            self.assertEqual(ns.scope.channel_types, ["CHANNEL"])


class BaselineRoundTripTests(TestCase):
    """The bare `.operations-{stem}` baseline is owned by `write_baseline`; the
    Operations panel never touches it, but tests and future migrations need to."""

    def test_baseline_crawl_round_trip(self) -> None:
        with _RedirectConfigPaths() as tmp:
            write_baseline(
                "crawl_channels",
                {
                    "downloads": {"video": True},
                    "scope": {"channel_types": ["CHANNEL", "GROUP"]},
                    "channels": {"get_channels_info": True},
                },
            )
            self.assertTrue((tmp / ".operations-crawl").exists())
            ns = load_crawl_settings(hermetic=False)
            self.assertEqual(ns.downloads.video, True)
            self.assertEqual(ns.downloads.images, False)
            self.assertEqual(ns.scope.channel_types, ["CHANNEL", "GROUP"])
            self.assertEqual(ns.channels.get_channels_info, True)

    def test_baseline_structural_round_trip(self) -> None:
        with _RedirectConfigPaths() as tmp:
            write_baseline(
                "structural_analysis",
                {
                    "outputs": {"graph": True, "html": True},
                    "measures": {"selected": ["PAGERANK", "BETWEENNESS"]},
                    "robustness": {"strategies": ["pagerank"]},
                },
            )
            self.assertTrue((tmp / ".operations-structural").exists())
            ns = load_structural_settings(hermetic=False)
            self.assertEqual(ns.outputs.graph, True)
            self.assertEqual(ns.outputs.html, True)
            self.assertEqual(ns.outputs.xlsx, False)
            self.assertEqual(ns.measures.selected, ["PAGERANK", "BETWEENNESS"])
            self.assertEqual(ns.robustness.strategies, ["pagerank"])
            # `communities.strategies` defaults to [] (factory-empty no-op);
            # not provided in the write_baseline payload above, so still [].
            self.assertEqual(ns.communities.strategies, [])


class NamedSnapshotTests(TestCase):
    """`save_named` always creates a fresh timestamped sidecar — never overwrites
    the baseline."""

    def test_save_named_creates_timestamped_file(self) -> None:
        with _RedirectConfigPaths() as tmp:
            item = save_named(
                "crawl_channels",
                {"downloads": {"audio": True}},
                title="My setup",
            )
            self.assertFalse(item["is_base"])
            self.assertTrue((tmp / item["filename"]).exists())
            self.assertEqual(item["title"], "My setup")
            self.assertNotEqual(item["id"], "base")
            content = (tmp / item["filename"]).read_text()
            self.assertIn("[meta]", content)
            self.assertIn('title = "My setup"', content)
            self.assertIn("audio = true", content)

    def test_save_named_does_not_touch_baseline(self) -> None:
        with _RedirectConfigPaths() as tmp:
            write_baseline("crawl_channels", {"downloads": {"images": True}})
            baseline_content = (tmp / ".operations-crawl").read_text()
            save_named("crawl_channels", {"downloads": {"audio": True}}, title="Sidecar")
            self.assertEqual((tmp / ".operations-crawl").read_text(), baseline_content)

    def test_save_named_rejects_empty_title(self) -> None:
        with _RedirectConfigPaths():
            with self.assertRaises(ValueError):
                save_named("crawl_channels", {}, title="   ")

    def test_load_payload_by_id_returns_snapshot_values(self) -> None:
        with _RedirectConfigPaths():
            item = save_named("crawl_channels", {"downloads": {"audio": True}}, title="S1")
            merged = load_payload_by_id("crawl_channels", item["id"])
            self.assertIsNotNone(merged)
            self.assertEqual(merged["downloads"]["audio"], True)
            # Untouched defaults from defaults.py still merged in.
            self.assertEqual(merged["scope"]["channel_types"], ["CHANNEL"])

    def test_load_payload_by_id_returns_none_for_unknown_id(self) -> None:
        with _RedirectConfigPaths():
            self.assertIsNone(load_payload_by_id("crawl_channels", "2099-01-01T00-00-00Z"))


class ListDefaultsTests(TestCase):
    def test_base_first_then_newest_snapshots(self) -> None:
        with _RedirectConfigPaths():
            write_baseline("crawl_channels", {"downloads": {"images": True}})
            first = save_named("crawl_channels", {}, title="First")
            second = save_named("crawl_channels", {}, title="Second")
            items = list_defaults("crawl_channels")
            self.assertEqual(items[0]["id"], "base")
            self.assertTrue(items[0]["is_base"])
            # Newest first: `second` has a >= timestamp to `first`.
            saved_ids = [it["id"] for it in items[1:]]
            self.assertIn(first["id"], saved_ids)
            self.assertIn(second["id"], saved_ids)
            self.assertEqual(saved_ids, sorted(saved_ids, reverse=True))

    def test_skips_files_with_invalid_id(self) -> None:
        with _RedirectConfigPaths() as tmp:
            write_baseline("crawl_channels", {})
            # A sidecar with a malformed id stem must not appear in the listing.
            (tmp / ".operations-crawl-not-a-timestamp").write_text("# noise\n")
            ids = [it["id"] for it in list_defaults("crawl_channels")]
            self.assertEqual(ids, ["base"])


class VersionStampTests(TestCase):
    def test_pulpit_version_field_written_and_readable(self) -> None:
        with _RedirectConfigPaths() as tmp:
            item = save_named("crawl_channels", {"downloads": {"images": True}}, title="T")
            version = read_pulpit_version(tmp / item["filename"])
            self.assertIsNotNone(version)
            self.assertNotEqual(version, "")


class CommentPreservationTests(TestCase):
    """tomlkit must keep hand-written comments alive inside a snapshot the user
    later modifies by hand. (The Operations panel never rewrites snapshots —
    they're one-shot — but `write_baseline` does, so it's the relevant test.)"""

    def test_user_comment_survives_baseline_rewrite(self) -> None:
        with _RedirectConfigPaths() as tmp:
            write_baseline("crawl_channels", {"telegram": {"connection_retries": 50}})
            content = (tmp / ".operations-crawl").read_text()
            content = content.replace("[telegram]", "[telegram]\n# user note: do not bump this number")
            (tmp / ".operations-crawl").write_text(content)
            write_baseline("crawl_channels", {"downloads": {"audio": True}})
            final = (tmp / ".operations-crawl").read_text()
            self.assertIn("audio = true", final)


class MalformedTOMLFallbackTests(TestCase):
    def test_malformed_file_falls_back_to_defaults(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-crawl").write_text("this is = not valid toml [[[")
            ns = load_crawl_settings(hermetic=False)
            # Falls back to built-in defaults — no telegram block expected anymore.
            self.assertEqual(ns.downloads.images, False)
            self.assertEqual(ns.channels.get_channels_info, False)


class LegacyTelegramSectionTests(TestCase):
    """Pre-.env-migration snapshots carry a [telegram] block that must be
    silently stripped on load (the values now live in `.env`)."""

    def test_legacy_telegram_block_is_dropped(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-crawl").write_text(
                '[telegram]\nsession_name = "old"\nconnection_retries = 42\n\n[downloads]\nimages = true\n'
            )
            ns = load_crawl_settings(hermetic=False)
            self.assertFalse(hasattr(ns, "telegram"))
            self.assertEqual(ns.downloads.images, True)


class LegacyTopLevelHeaderTests(TestCase):
    """Pre-`[meta]` files that put pulpit_version/generated_at at the top level
    must still load (they only get stripped, not flagged as errors)."""

    def test_legacy_header_loads_cleanly(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-structural").write_text(
                'pulpit_version = "0.0"\n'
                'generated_at = "2020-01-01T00:00:00Z"\n'
                "[graph]\n"
                'community_palette = "ORGANIZATION"\n'
            )
            ns = load_structural_settings(hermetic=False)
            self.assertEqual(ns.graph.community_palette, "ORGANIZATION")


class LegacyBridgingBasisMigrationTests(TestCase):
    """v0.24→v0.25: the shared measures.bridging_basis is folded into the BRIDGING token and
    seeds the robustness panel's own basis; the old key is dropped."""

    def test_legacy_basis_folds_into_token_and_robustness(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-structural").write_text(
                "[measures]\n"
                'selected = ["PAGERANK", "BRIDGING"]\n'
                'bridging_basis = "LEIDEN"\n'
                "[robustness]\n"
                'strategies = ["bridging"]\n'
            )
            ns = load_structural_settings(hermetic=False)
            self.assertEqual(ns.measures.selected, ["PAGERANK", "BRIDGING(basis=LEIDEN)"])
            self.assertEqual(ns.robustness.bridging_basis, "LEIDEN")
            self.assertFalse(hasattr(ns.measures, "bridging_basis"))

    def test_new_file_with_per_instance_token_is_untouched(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-structural").write_text(
                '[measures]\nselected = ["BRIDGING(basis=LEIDEN_DIRECTED)", "SPREADING(runs=2000)"]\n'
            )
            ns = load_structural_settings(hermetic=False)
            self.assertEqual(ns.measures.selected, ["BRIDGING(basis=LEIDEN_DIRECTED)", "SPREADING(runs=2000)"])


class LegacyCommunityParamsMigrationTests(TestCase):
    """v0.24→v0.25: the fixed LEIDEN_CPM_COARSE/FINE presets and the [computation] CPM/MCL keys fold
    into per-instance LEIDEN_CPM(resolution=…) / MCL(inflation=…) tokens; the old keys are dropped."""

    def test_legacy_presets_fold_into_tokens(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-structural").write_text(
                "[communities]\n"
                'strategies = ["ORGANIZATION", "LEIDEN_CPM_COARSE", "LEIDEN_CPM_FINE", "MCL"]\n'
                "[computation]\n"
                "leiden_coarse_resolution = 0.01\n"
                "leiden_fine_resolution = 0.05\n"
                "mcl_inflation = 3.0\n"
            )
            ns = load_structural_settings(hermetic=False)
            self.assertEqual(
                ns.communities.strategies,
                ["ORGANIZATION", "LEIDEN_CPM(resolution=0.01)", "LEIDEN_CPM(resolution=0.05)", "MCL(inflation=3.0)"],
            )
            self.assertFalse(hasattr(ns.computation, "leiden_coarse_resolution"))
            self.assertFalse(hasattr(ns.computation, "mcl_inflation"))

    def test_new_file_with_per_instance_tokens_untouched(self) -> None:
        with _RedirectConfigPaths() as tmp:
            (tmp / ".operations-structural").write_text(
                '[communities]\nstrategies = ["LEIDEN_DIRECTED", "LEIDEN_CPM(resolution=0.02)"]\n'
            )
            ns = load_structural_settings(hermetic=False)
            self.assertEqual(ns.communities.strategies, ["LEIDEN_DIRECTED", "LEIDEN_CPM(resolution=0.02)"])
