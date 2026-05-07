"""Tests for webapp: color utilities, managers, models, views, paginator."""

from __future__ import annotations

import datetime

from django.core.paginator import InvalidPage
from django.test import TestCase
from django.urls import reverse

from network.graph_builder import channel_network_data
from webapp.managers import ChannelManager, ChannelQuerySet
from webapp.models import Channel, Message, Organization
from webapp.paginator import DiggPage, DiggPaginator, SoftPaginator
from webapp.utils.colors import (
    DEFAULT_FALLBACK_COLOR,
    average_color,
    expand_colors,
    hex_to_rgb,
    is_color_dark,
    parse_color,
    rgb_avg,
    rgb_to_hex,
)

# ─── hex_to_rgb ────────────────────────────────────────────────────────────────


class HexToRgbTests(TestCase):
    def test_six_char_with_hash(self) -> None:
        self.assertEqual(hex_to_rgb("#ff0000"), (255, 0, 0))

    def test_six_char_without_hash(self) -> None:
        self.assertEqual(hex_to_rgb("ff0000"), (255, 0, 0))

    def test_three_char_with_hash(self) -> None:
        self.assertEqual(hex_to_rgb("#f00"), (255, 0, 0))

    def test_three_char_without_hash(self) -> None:
        self.assertEqual(hex_to_rgb("f00"), (255, 0, 0))

    def test_white(self) -> None:
        self.assertEqual(hex_to_rgb("#ffffff"), (255, 255, 255))

    def test_black(self) -> None:
        self.assertEqual(hex_to_rgb("#000000"), (0, 0, 0))

    def test_mixed_case(self) -> None:
        self.assertEqual(hex_to_rgb("#FF0000"), (255, 0, 0))

    def test_three_char_expands_each_nibble(self) -> None:
        # #abc → CSS shorthand expansion → #aabbcc → (0xAA, 0xBB, 0xCC)
        r, g, b = hex_to_rgb("#abc")
        self.assertEqual(r, 0xAA)
        self.assertEqual(g, 0xBB)
        self.assertEqual(b, 0xCC)

    def test_specific_channel_values(self) -> None:
        r, g, b = hex_to_rgb("#1a2b3c")
        self.assertEqual(r, 0x1A)
        self.assertEqual(g, 0x2B)
        self.assertEqual(b, 0x3C)

    def test_invalid_length_four_chars_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            hex_to_rgb("ff00")

    def test_invalid_length_empty_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            hex_to_rgb("")

    def test_invalid_length_two_chars_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            hex_to_rgb("ff")


# ─── rgb_to_hex ────────────────────────────────────────────────────────────────


class RgbToHexTests(TestCase):
    def test_red(self) -> None:
        self.assertEqual(rgb_to_hex((255, 0, 0)), "#ff0000")

    def test_black(self) -> None:
        self.assertEqual(rgb_to_hex((0, 0, 0)), "#000000")

    def test_white(self) -> None:
        self.assertEqual(rgb_to_hex((255, 255, 255)), "#ffffff")

    def test_list_input_accepted(self) -> None:
        self.assertEqual(rgb_to_hex([128, 64, 32]), "#804020")

    def test_zero_padding(self) -> None:
        self.assertEqual(rgb_to_hex((0, 15, 255)), "#000fff")

    def test_string_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            rgb_to_hex("#ff0000")

    def test_roundtrip_with_hex_to_rgb(self) -> None:
        original = "#4a90e2"
        self.assertEqual(rgb_to_hex(hex_to_rgb(original)), original)


# ─── is_color_dark ─────────────────────────────────────────────────────────────


class IsColorDarkTests(TestCase):
    def test_black_is_dark(self) -> None:
        self.assertTrue(is_color_dark("#000000"))

    def test_white_is_not_dark(self) -> None:
        self.assertFalse(is_color_dark("#ffffff"))

    def test_pure_red_is_dark(self) -> None:
        # 0.2126 * 255 ≈ 54 < 128
        self.assertTrue(is_color_dark("#ff0000"))

    def test_pure_green_is_not_dark(self) -> None:
        # 0.7152 * 255 ≈ 182 > 128
        self.assertFalse(is_color_dark("#00ff00"))

    def test_pure_blue_is_dark(self) -> None:
        # 0.0722 * 255 ≈ 18 < 128
        self.assertTrue(is_color_dark("#0000ff"))

    def test_dark_grey_is_dark(self) -> None:
        self.assertTrue(is_color_dark("#404040"))

    def test_light_grey_is_not_dark(self) -> None:
        self.assertFalse(is_color_dark("#c0c0c0"))


# ─── rgb_avg ───────────────────────────────────────────────────────────────────


class RgbAvgTests(TestCase):
    def test_average_of_two_distinct_colors(self) -> None:
        self.assertEqual(rgb_avg((100, 200, 50), (200, 100, 150)), (150, 150, 100))

    def test_same_color_returns_same(self) -> None:
        color = (120, 80, 200)
        self.assertEqual(rgb_avg(color, color), color)

    def test_black_and_even_white(self) -> None:
        result = rgb_avg((0, 0, 0), (254, 254, 254))
        self.assertEqual(result, (127, 127, 127))

    def test_returns_three_element_tuple(self) -> None:
        result = rgb_avg((10, 20, 30), (40, 50, 60))
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)


# ─── parse_color ───────────────────────────────────────────────────────────────


class ParseColorTests(TestCase):
    """parse_color() must handle every supported color representation."""

    # Hex strings
    def test_hex_with_hash(self) -> None:
        self.assertEqual(parse_color("#ff0000"), (255, 0, 0))

    def test_hex_without_hash(self) -> None:
        self.assertEqual(parse_color("ff0000"), (255, 0, 0))

    def test_three_char_hex(self) -> None:
        self.assertEqual(parse_color("#f00"), (255, 0, 0))

    def test_0x_prefix_stripped(self) -> None:
        self.assertEqual(parse_color("0xff0000"), (255, 0, 0))

    def test_eight_char_hex_strips_last_two(self) -> None:
        self.assertEqual(parse_color("ff000080"), (255, 0, 0))

    def test_eight_char_hex_with_hash_strips_alpha(self) -> None:
        self.assertEqual(parse_color("#ff000080"), (255, 0, 0))

    def test_four_char_hex_strips_last_one(self) -> None:
        self.assertEqual(parse_color("f00f"), (255, 0, 0))

    # RGB strings
    def test_rgb_string_255_range(self) -> None:
        self.assertEqual(parse_color("rgb(255, 0, 128)"), (255, 0, 128))

    def test_rgb_string_01_range(self) -> None:
        self.assertEqual(parse_color("rgb(1.0, 0.0, 0.5)"), (255, 0, 127))

    def test_rgba_string_parsed(self) -> None:
        self.assertEqual(parse_color("rgba(100, 150, 200)"), (100, 150, 200))

    def test_rgb_string_empty_parens_returns_fallback(self) -> None:
        self.assertEqual(parse_color("rgb()"), DEFAULT_FALLBACK_COLOR)

    # Comma-separated strings
    def test_comma_separated_255_range(self) -> None:
        self.assertEqual(parse_color("255,0,128"), (255, 0, 128))

    def test_comma_separated_01_range(self) -> None:
        self.assertEqual(parse_color("1.0,0.0,0.5"), (255, 0, 127))

    def test_comma_separated_too_short_returns_fallback(self) -> None:
        self.assertEqual(parse_color("255,0"), DEFAULT_FALLBACK_COLOR)

    def test_comma_separated_with_spaces(self) -> None:
        self.assertEqual(parse_color("255, 0, 128"), (255, 0, 128))

    # Space-separated strings
    def test_space_separated_255_range(self) -> None:
        self.assertEqual(parse_color("255 0 128"), (255, 0, 128))

    # Tuple / list
    def test_tuple_255_range(self) -> None:
        self.assertEqual(parse_color((255, 0, 128)), (255, 0, 128))

    def test_list_255_range(self) -> None:
        self.assertEqual(parse_color([128, 64, 32]), (128, 64, 32))

    def test_tuple_01_range(self) -> None:
        self.assertEqual(parse_color((1.0, 0.0, 0.5)), (255, 0, 127))

    # Dict
    def test_dict_r_g_b_keys(self) -> None:
        self.assertEqual(parse_color({"r": 255, "g": 0, "b": 128}), (255, 0, 128))

    def test_dict_red_green_blue_keys(self) -> None:
        self.assertEqual(parse_color({"red": 100, "green": 150, "blue": 200}), (100, 150, 200))

    # Objects with attributes
    def test_object_with_hex_attribute(self) -> None:
        class FakeColor:
            hex = "#ff0000"

        self.assertEqual(parse_color(FakeColor()), (255, 0, 0))

    def test_object_with_hex_code_attribute(self) -> None:
        class FakeColor:
            hex_code = "#00ff00"

        self.assertEqual(parse_color(FakeColor()), (0, 255, 0))

    def test_object_with_rgb_attribute(self) -> None:
        class FakeColor:
            rgb = (128, 64, 32)

        self.assertEqual(parse_color(FakeColor()), (128, 64, 32))

    def test_object_with_rgba_attribute(self) -> None:
        class FakeColor:
            rgba = (10, 20, 30, 255)

        result = parse_color(FakeColor())
        self.assertEqual(result[:3], (10, 20, 30))

    # Fallback
    def test_invalid_string_returns_fallback(self) -> None:
        self.assertEqual(parse_color("notacolor"), DEFAULT_FALLBACK_COLOR)

    def test_none_returns_fallback(self) -> None:
        self.assertEqual(parse_color(None), DEFAULT_FALLBACK_COLOR)

    def test_integer_returns_fallback(self) -> None:
        self.assertEqual(parse_color(42), DEFAULT_FALLBACK_COLOR)

    def test_two_char_string_returns_fallback(self) -> None:
        self.assertEqual(parse_color("ab"), DEFAULT_FALLBACK_COLOR)


# ─── expand_colors ─────────────────────────────────────────────────────────────


class ExpandColorsTests(TestCase):
    def test_exact_count_returns_same_list(self) -> None:
        colors = [(255, 0, 0), (0, 255, 0)]
        self.assertEqual(expand_colors(colors, 2), list(colors))

    def test_expand_single_color_by_repetition(self) -> None:
        self.assertEqual(expand_colors([(255, 0, 0)], 3), [(255, 0, 0)] * 3)

    def test_truncate_when_more_than_needed(self) -> None:
        colors = [(1, 1, 1), (2, 2, 2), (3, 3, 3)]
        self.assertEqual(expand_colors(colors, 2), [(1, 1, 1), (2, 2, 2)])

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(expand_colors([], 5), [])

    def test_partial_repeat_preserves_order(self) -> None:
        colors = [(1, 1, 1), (2, 2, 2), (3, 3, 3)]
        self.assertEqual(expand_colors(colors, 5), [(1, 1, 1), (2, 2, 2), (3, 3, 3), (1, 1, 1), (2, 2, 2)])

    def test_zero_count_returns_empty(self) -> None:
        self.assertEqual(expand_colors([(1, 2, 3)], 0), [])


# ─── average_color ─────────────────────────────────────────────────────────────


class AverageColorTests(TestCase):
    def test_empty_list_returns_fallback(self) -> None:
        self.assertEqual(average_color([]), DEFAULT_FALLBACK_COLOR)

    def test_single_hex_color(self) -> None:
        self.assertEqual(average_color(["#ff0000"]), (255, 0, 0))

    def test_two_opposite_colors_midpoint(self) -> None:
        self.assertEqual(average_color(["#000000", "#ffffff"]), (127, 127, 127))

    def test_three_rgb_tuples(self) -> None:
        result = average_color([(90, 120, 150), (30, 60, 90), (60, 60, 60)])
        self.assertEqual(result, (60, 80, 100))

    def test_result_has_three_channels(self) -> None:
        self.assertEqual(len(average_color([(100, 100, 100)])), 3)


# ─── ChannelManager ────────────────────────────────────────────────────────────


class ChannelManagerTests(TestCase):
    def setUp(self) -> None:
        self.interesting_org = Organization.objects.create(name="Interesting", is_interesting=True)
        self.boring_org = Organization.objects.create(name="Boring", is_interesting=False)
        self.ch_interesting = Channel.objects.create(
            telegram_id=1, title="Channel A", organization=self.interesting_org
        )
        self.ch_boring = Channel.objects.create(telegram_id=2, title="Channel B", organization=self.boring_org)
        self.ch_orphan = Channel.objects.create(telegram_id=3, title="Channel C")

    def test_interesting_includes_interesting_org_channel(self) -> None:
        self.assertIn(self.ch_interesting, Channel.objects.interesting())

    def test_interesting_excludes_boring_org_channel(self) -> None:
        self.assertNotIn(self.ch_boring, Channel.objects.interesting())

    def test_interesting_excludes_channel_with_no_org(self) -> None:
        self.assertNotIn(self.ch_orphan, Channel.objects.interesting())

    def test_objects_is_channel_manager(self) -> None:
        self.assertIsInstance(Channel.objects, ChannelManager)

    def test_interesting_returns_channel_queryset(self) -> None:
        self.assertIsInstance(Channel.objects.interesting(), ChannelQuerySet)

    def test_interesting_queryset_is_chainable(self) -> None:
        qs = Channel.objects.interesting().filter(title="Channel A")
        self.assertEqual(list(qs), [self.ch_interesting])

    def test_interesting_count(self) -> None:
        self.assertEqual(Channel.objects.interesting().count(), 1)


# ─── Channel model ─────────────────────────────────────────────────────────────


class ChannelStrTests(TestCase):
    def test_str_returns_title(self) -> None:
        self.assertEqual(str(Channel(telegram_id=1, title="My Channel")), "My Channel")

    def test_str_fallback_to_telegram_id_when_empty_title(self) -> None:
        self.assertEqual(str(Channel(telegram_id=42, title="")), "42")


class ChannelTelegramUrlTests(TestCase):
    def test_url_uses_username(self) -> None:
        self.assertEqual(Channel(telegram_id=1, username="mychannel").telegram_url, "https://t.me/mychannel")

    def test_url_falls_back_to_telegram_id(self) -> None:
        self.assertEqual(Channel(telegram_id=999, username="").telegram_url, "https://t.me/999")


class ChannelGetAbsoluteUrlTests(TestCase):
    def test_returns_detail_url(self) -> None:
        ch = Channel.objects.create(telegram_id=1, title="Ch")
        self.assertEqual(ch.get_absolute_url(), reverse("channel-detail", kwargs={"pk": ch.pk}))


class ChannelSaveTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org", is_interesting=True)
        self.ch1 = Channel.objects.create(telegram_id=1, title="Source", organization=self.org)
        self.ch2 = Channel.objects.create(telegram_id=2, title="Target", organization=self.org)

    def test_none_username_converted_to_empty_string(self) -> None:
        ch = Channel(telegram_id=99, title="X", username=None)
        ch.save()
        self.assertEqual(ch.username, "")

    def test_existing_username_preserved(self) -> None:
        ch = Channel.objects.create(telegram_id=100, username="handle")
        self.assertEqual(ch.username, "handle")

    def test_in_degree_counts_forwards_from_interesting_channels(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.ch2, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.in_degree, 1)

    def test_in_degree_excludes_self_forwards(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.ch1, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.in_degree, 0)

    def test_in_degree_excludes_non_interesting_org(self) -> None:
        boring = Organization.objects.create(name="Boring", is_interesting=False)
        boring_ch = Channel.objects.create(telegram_id=50, organization=boring)
        Message.objects.create(telegram_id=10, channel=boring_ch, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.in_degree, 0)

    def test_out_degree_counts_forwards_to_interesting_channels(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.ch1, forwarded_from=self.ch2)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.out_degree, 1)

    def test_out_degree_excludes_self_forwards(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.ch1, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.out_degree, 0)

    def test_instance_fields_synced_after_refresh_degrees(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.ch2, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.assertEqual(self.ch1.in_degree, 1)

    def test_refresh_degrees_uses_update_not_full_save(self) -> None:
        """Degree recalculation must use queryset.update(), not a full model save."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.ch1.refresh_degrees()
        sql_upper = [q["sql"].upper() for q in ctx.captured_queries]
        update_count = sum(1 for s in sql_upper if s.startswith("UPDATE"))
        # Exactly one UPDATE from queryset.update() — no full model save
        self.assertEqual(update_count, 1)


class ChannelActivityPeriodTests(TestCase):
    def setUp(self) -> None:
        self.ch = Channel.objects.create(telegram_id=1)

    def test_no_date_no_messages_returns_unknown(self) -> None:
        self.assertEqual(self.ch.activity_period, "Unknown")

    def test_channel_date_alone_used_when_no_messages(self) -> None:
        self.ch.date = datetime.datetime(2020, 3, 1, tzinfo=datetime.timezone.utc)
        self.ch.save()
        result = self.ch.activity_period
        self.assertIn("Mar 2020", result)

    def test_messages_determine_start(self) -> None:
        Message.objects.create(
            telegram_id=1, channel=self.ch, date=datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
        )
        Message.objects.create(
            telegram_id=2, channel=self.ch, date=datetime.datetime(2023, 6, 1, tzinfo=datetime.timezone.utc)
        )
        self.assertIn("Jan 2023", self.ch.activity_period)

    def test_channel_date_earlier_than_messages_used_as_start(self) -> None:
        self.ch.date = datetime.datetime(2020, 3, 1, tzinfo=datetime.timezone.utc)
        self.ch.save()
        Message.objects.create(
            telegram_id=1, channel=self.ch, date=datetime.datetime(2023, 6, 1, tzinfo=datetime.timezone.utc)
        )
        self.assertIn("Mar 2020", self.ch.activity_period)

    def test_null_dated_messages_are_ignored(self) -> None:
        Message.objects.create(telegram_id=1, channel=self.ch, date=None)
        self.assertEqual(self.ch.activity_period, "Unknown")

    def test_recent_end_date_shows_open_ended_format(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        Message.objects.create(telegram_id=1, channel=self.ch, date=now - datetime.timedelta(days=1))
        self.assertTrue(self.ch.activity_period.endswith("- "))

    def test_old_end_date_shows_closed_range(self) -> None:
        old = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        Message.objects.create(telegram_id=1, channel=self.ch, date=old)
        self.assertIn("Jan 2020 - Jan 2020", self.ch.activity_period)

    def test_uses_single_db_query(self) -> None:
        Message.objects.create(
            telegram_id=1, channel=self.ch, date=datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
        )
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            _ = self.ch.activity_period
        self.assertEqual(len(ctx.captured_queries), 1)


class ChannelNetworkDataTests(TestCase):
    def test_with_organization_sets_label(self) -> None:
        org = Organization.objects.create(name="Test Org", color="#ff0000")
        ch = Channel.objects.create(telegram_id=1, title="Chan", organization=org)
        data = channel_network_data(ch)
        self.assertEqual(data["label"], "Chan")

    def test_communities_is_empty_dict_initially(self) -> None:
        ch = Channel.objects.create(telegram_id=1, title="Chan")
        data = channel_network_data(ch)
        self.assertEqual(data["communities"], {})

    def test_required_keys_present(self) -> None:
        ch = Channel.objects.create(telegram_id=1, title="Chan")
        data = channel_network_data(ch)
        for key in ("pk", "id", "label", "communities", "color", "url", "activity_period", "fans"):
            self.assertIn(key, data, msg=f"Missing key: {key}")

    def test_defaults_dict_merged(self) -> None:
        ch = Channel.objects.create(telegram_id=1, title="Chan")
        data = channel_network_data(ch, {"extra": "value"})
        self.assertEqual(data["extra"], "value")

    def test_defaults_override_computed_fields(self) -> None:
        ch = Channel.objects.create(telegram_id=1, title="Original")
        data = channel_network_data(ch, {"label": "Override"})
        self.assertEqual(data["label"], "Override")


# ─── Message model ─────────────────────────────────────────────────────────────


class MessageSaveTests(TestCase):
    def setUp(self) -> None:
        self.ch = Channel.objects.create(telegram_id=1, title="Ch")

    def test_none_message_converted_to_empty_string(self) -> None:
        msg = Message(telegram_id=1, channel=self.ch, message=None)
        msg.save()
        self.assertEqual(msg.message, "")

    def test_none_webpage_url_converted_to_empty_string(self) -> None:
        msg = Message.objects.create(telegram_id=1, channel=self.ch)
        self.assertEqual(msg.webpage_url, "")

    def test_none_webpage_type_converted_to_empty_string(self) -> None:
        msg = Message.objects.create(telegram_id=1, channel=self.ch)
        self.assertEqual(msg.webpage_type, "")

    def test_pinned_true_sets_has_been_pinned(self) -> None:
        msg = Message.objects.create(telegram_id=1, channel=self.ch, pinned=True)
        self.assertTrue(msg.has_been_pinned)

    def test_pinned_false_leaves_has_been_pinned_false(self) -> None:
        msg = Message.objects.create(telegram_id=1, channel=self.ch, pinned=False)
        self.assertFalse(msg.has_been_pinned)

    def test_has_been_pinned_persisted_to_db(self) -> None:
        msg = Message.objects.create(telegram_id=1, channel=self.ch, pinned=True)
        msg.refresh_from_db()
        self.assertTrue(msg.has_been_pinned)

    def test_existing_text_preserved(self) -> None:
        msg = Message.objects.create(telegram_id=1, channel=self.ch, message="Hello")
        self.assertEqual(msg.message, "Hello")

    def test_single_insert_when_not_pinned(self) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        msg = Message(telegram_id=1, channel=self.ch, pinned=False)
        with CaptureQueriesContext(connection) as ctx:
            msg.save()
        inserts = [q for q in ctx.captured_queries if q["sql"].upper().startswith("INSERT")]
        self.assertEqual(len(inserts), 1)

    def test_single_insert_even_when_pinned(self) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        msg = Message(telegram_id=1, channel=self.ch, pinned=True)
        with CaptureQueriesContext(connection) as ctx:
            msg.save()
        inserts = [q for q in ctx.captured_queries if q["sql"].upper().startswith("INSERT")]
        self.assertEqual(len(inserts), 1)


class MessageGetTelegramReferencesTests(TestCase):
    def test_extracts_username(self) -> None:
        msg = Message(message="Check t.me/somechannel for info")
        self.assertIn("somechannel", msg.get_telegram_references())

    def test_no_links_returns_empty(self) -> None:
        self.assertEqual(Message(message="No links here").get_telegram_references(), [])

    def test_extracts_multiple_links(self) -> None:
        refs = Message(message="t.me/chan1 and t.me/chan2").get_telegram_references()
        self.assertIn("chan1", refs)
        self.assertIn("chan2", refs)
        self.assertEqual(len(refs), 2)

    def test_handles_hyphenated_username(self) -> None:
        self.assertIn("some-channel", Message(message="t.me/some-channel").get_telegram_references())

    def test_handles_underscored_username(self) -> None:
        self.assertIn("my_channel", Message(message="t.me/my_channel").get_telegram_references())

    def test_empty_message_returns_empty(self) -> None:
        self.assertEqual(Message(message="").get_telegram_references(), [])

    def test_duplicate_links_each_included(self) -> None:
        refs = Message(message="t.me/chan t.me/chan").get_telegram_references()
        self.assertEqual(refs.count("chan"), 2)


class MessageTelegramUrlTests(TestCase):
    def test_url_combines_channel_url_and_message_id(self) -> None:
        ch = Channel.objects.create(telegram_id=1, username="mychan")
        msg = Message.objects.create(telegram_id=42, channel=ch)
        self.assertEqual(msg.telegram_url, "https://t.me/mychan/42")


# ─── TelegramBaseModel.from_telegram_object ────────────────────────────────────


class FromTelegramObjectTests(TestCase):
    """Tests for the shared factory classmethod using Channel as the concrete model."""

    class _Fake:
        id = 999
        title = "Fake Channel"
        username = "fakechan"
        date = None
        broadcast = True
        verified = False
        megagroup = False
        gigagroup = False
        restricted = False
        signatures = False
        min = False
        scam = False
        has_link = False
        has_geo = False
        slowmode_enabled = False
        fake = False
        access_hash = None

    def test_creates_new_object(self) -> None:
        obj = Channel.from_telegram_object(self._Fake())
        self.assertIsNotNone(obj.pk)
        self.assertEqual(obj.telegram_id, 999)

    def test_second_call_returns_same_object(self) -> None:
        obj1 = Channel.from_telegram_object(self._Fake())
        obj2 = Channel.from_telegram_object(self._Fake(), force_update=False)
        self.assertEqual(obj1.pk, obj2.pk)
        self.assertEqual(Channel.objects.filter(telegram_id=999).count(), 1)

    def test_force_update_refreshes_properties(self) -> None:
        Channel.from_telegram_object(self._Fake())

        class Updated(self._Fake):
            title = "Updated Title"

        obj = Channel.from_telegram_object(Updated(), force_update=True)
        self.assertEqual(obj.title, "Updated Title")

    def test_no_force_update_leaves_existing_properties(self) -> None:
        Channel.from_telegram_object(self._Fake())

        class Altered(self._Fake):
            title = "Should Not Appear"

        Channel.from_telegram_object(Altered(), force_update=False)
        self.assertEqual(Channel.objects.get(telegram_id=999).title, "Fake Channel")

    def test_defaults_applied_on_creation(self) -> None:
        org = Organization.objects.create(name="D Org")

        class OtherFake(self._Fake):
            id = 888

        obj = Channel.from_telegram_object(OtherFake(), defaults={"organization": org})
        self.assertEqual(obj.organization, org)


# ─── Organization model ────────────────────────────────────────────────────────


class OrganizationModelTests(TestCase):
    def test_str_returns_name(self) -> None:
        self.assertEqual(str(Organization(name="Test")), "Test")

    def test_key_is_slugified(self) -> None:
        self.assertEqual(Organization(name="My Cool Org").key, "my-cool-org")

    def test_key_only_alphanumeric_and_hyphens(self) -> None:
        self.assertRegex(Organization(name="Org, Inc.").key, r"^[a-z0-9-]+$")

    def test_is_color_dark_for_black(self) -> None:
        self.assertTrue(Organization(color="#000000").is_color_dark)

    def test_is_color_dark_for_white(self) -> None:
        self.assertFalse(Organization(color="#ffffff").is_color_dark)


# ─── HomeView ──────────────────────────────────────────────────────────────────


class HomeViewTests(TestCase):
    def test_get_returns_200(self) -> None:
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)


# ─── ChannelDetailView ─────────────────────────────────────────────────────────


class ChannelDetailViewTests(TestCase):
    def setUp(self) -> None:
        self.ch = Channel.objects.create(telegram_id=1, title="Test Channel")
        for i in range(3):
            Message.objects.create(
                telegram_id=i,
                channel=self.ch,
                date=datetime.datetime(2023, 1, i + 1, tzinfo=datetime.timezone.utc),
            )

    def test_get_returns_200(self) -> None:
        self.assertEqual(self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk})).status_code, 200)

    def test_nonexistent_channel_returns_404(self) -> None:
        self.assertEqual(self.client.get(reverse("channel-detail", kwargs={"pk": 99999})).status_code, 404)

    def test_selected_channel_in_context(self) -> None:
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}))
        self.assertEqual(response.context["selected_channel"], self.ch)

    def test_messages_ordered_by_date(self) -> None:
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}))
        dates = [m.date for m in response.context["object_list"] if m.date]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_only_messages_for_selected_channel(self) -> None:
        other = Channel.objects.create(telegram_id=2, title="Other")
        Message.objects.create(telegram_id=99, channel=other)
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}))
        channel_ids = {m.channel_id for m in response.context["object_list"]}
        self.assertEqual(channel_ids, {self.ch.pk})

    def test_uses_digg_paginator(self) -> None:
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}))
        self.assertIsInstance(response.context["paginator"], DiggPaginator)


# ─── SoftPaginator ─────────────────────────────────────────────────────────────


class SoftPaginatorTests(TestCase):
    @staticmethod
    def _make(count: int = 100, per_page: int = 10) -> SoftPaginator:
        return SoftPaginator(range(count), per_page)

    def test_valid_page_returns_page(self) -> None:
        p = self._make()
        self.assertEqual(p.page(1).number, 1)

    def test_softlimit_redirects_out_of_range_to_last_page(self) -> None:
        p = self._make()
        self.assertEqual(p.page(9999, softlimit=True).number, p.num_pages)

    def test_without_softlimit_raises_invalid_page(self) -> None:
        with self.assertRaises(InvalidPage):
            self._make().page(9999, softlimit=False)

    def test_non_numeric_string_raises_invalid_page(self) -> None:
        with self.assertRaises(InvalidPage):
            self._make().page("not_a_number")

    def test_negative_page_raises_invalid_page(self) -> None:
        with self.assertRaises(InvalidPage):
            self._make().page(-1)


# ─── DiggPaginator / DiggPage ──────────────────────────────────────────────────


class DiggPaginatorTests(TestCase):
    @staticmethod
    def _make(count: int = 100, per_page: int = 10) -> DiggPaginator:
        return DiggPaginator(range(count), per_page)

    def test_page_returns_digg_page_instance(self) -> None:
        self.assertIsInstance(self._make().page(1), DiggPage)

    def test_out_of_range_soft_redirects_to_last(self) -> None:
        p = self._make()
        self.assertEqual(p.page(9999).number, p.num_pages)

    def test_elided_page_range_includes_page_one(self) -> None:
        self.assertIn(1, list(self._make().page(1).elided_page_range()))

    def test_elided_page_range_includes_current_page(self) -> None:
        self.assertIn(5, list(self._make().page(5).elided_page_range()))

    def test_correct_objects_on_last_partial_page(self) -> None:
        p = DiggPaginator(range(25), 10)
        self.assertEqual(len(p.page(3).object_list), 5)
