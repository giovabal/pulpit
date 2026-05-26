"""Tests for webapp: color utilities, managers, models, views, paginator."""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError
from django.core.paginator import InvalidPage
from django.test import TestCase
from django.urls import reverse

from network.graph_builder import channel_network_data
from webapp.managers import ChannelManager, ChannelQuerySet
from webapp.models import Channel, ChannelAttribution, ChannelVacancy, Message, Organization
from webapp.paginator import DiggPage, DiggPaginator, SoftPaginator
from webapp.test_helpers import attribute, make_channel
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
        self.in_target_org = Organization.objects.create(name="In target", is_in_target=True)
        self.boring_org = Organization.objects.create(name="Boring", is_in_target=False)
        self.ch_in_target = make_channel(telegram_id=1, title="Channel A", organization=self.in_target_org)
        self.ch_boring = make_channel(telegram_id=2, title="Channel B", organization=self.boring_org)
        self.ch_orphan = make_channel(telegram_id=3, title="Channel C")

    def test_in_target_includes_in_target_org_channel(self) -> None:
        self.assertIn(self.ch_in_target, Channel.objects.in_target())

    def test_in_target_excludes_boring_org_channel(self) -> None:
        self.assertNotIn(self.ch_boring, Channel.objects.in_target())

    def test_in_target_excludes_channel_with_no_org(self) -> None:
        self.assertNotIn(self.ch_orphan, Channel.objects.in_target())

    def test_objects_is_channel_manager(self) -> None:
        self.assertIsInstance(Channel.objects, ChannelManager)

    def test_in_target_returns_channel_queryset(self) -> None:
        self.assertIsInstance(Channel.objects.in_target(), ChannelQuerySet)

    def test_in_target_queryset_is_chainable(self) -> None:
        qs = Channel.objects.in_target().filter(title="Channel A")
        self.assertEqual(list(qs), [self.ch_in_target])

    def test_in_target_count(self) -> None:
        self.assertEqual(Channel.objects.in_target().count(), 1)


# ─── MessageManager ────────────────────────────────────────────────────────────


class MessageManagerTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="In target", is_in_target=True)
        self.ch = make_channel(telegram_id=1, title="Ch", organization=org)
        self.alive_msg = Message.objects.create(telegram_id=10, channel=self.ch, is_lost=False)
        self.lost_msg = Message.objects.create(telegram_id=11, channel=self.ch, is_lost=True)

    def test_alive_excludes_lost(self) -> None:
        alive_pks = list(Message.objects.alive().values_list("pk", flat=True))
        self.assertIn(self.alive_msg.pk, alive_pks)
        self.assertNotIn(self.lost_msg.pk, alive_pks)

    def test_default_queryset_includes_lost(self) -> None:
        all_pks = list(Message.objects.values_list("pk", flat=True))
        self.assertIn(self.alive_msg.pk, all_pks)
        self.assertIn(self.lost_msg.pk, all_pks)

    def test_alive_is_chainable(self) -> None:
        qs = Message.objects.alive().filter(channel=self.ch)
        self.assertEqual(qs.count(), 1)


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
        ch = make_channel(telegram_id=1, title="Ch")
        self.assertEqual(ch.get_absolute_url(), reverse("channel-detail", kwargs={"pk": ch.pk}))


class ChannelSaveTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org", is_in_target=True)
        self.ch1 = make_channel(telegram_id=1, title="Source", organization=self.org)
        self.ch2 = make_channel(telegram_id=2, title="Target", organization=self.org)

    def test_none_username_converted_to_empty_string(self) -> None:
        ch = Channel(telegram_id=99, title="X", username=None)
        ch.save()
        self.assertEqual(ch.username, "")

    def test_existing_username_preserved(self) -> None:
        ch = make_channel(telegram_id=100, username="handle")
        self.assertEqual(ch.username, "handle")

    def test_in_degree_counts_forwards_from_in_target_channels(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.ch2, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.in_degree, 1)

    def test_in_degree_excludes_self_forwards(self) -> None:
        Message.objects.create(telegram_id=10, channel=self.ch1, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.in_degree, 0)

    def test_in_degree_excludes_out_of_target_org(self) -> None:
        boring = Organization.objects.create(name="Boring", is_in_target=False)
        boring_ch = make_channel(telegram_id=50, organization=boring)
        Message.objects.create(telegram_id=10, channel=boring_ch, forwarded_from=self.ch1)
        self.ch1.refresh_degrees()
        self.ch1.refresh_from_db()
        self.assertEqual(self.ch1.in_degree, 0)

    def test_out_degree_counts_forwards_to_in_target_channels(self) -> None:
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
        self.ch = make_channel(telegram_id=1)

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

    def test_uses_minimal_db_queries(self) -> None:
        Message.objects.create(
            telegram_id=1, channel=self.ch, date=datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
        )
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            _ = self.ch.activity_period
        # One query to read in-target periods, one to aggregate the message-date bounds.
        self.assertEqual(len(ctx.captured_queries), 2)


class ChannelNetworkDataTests(TestCase):
    def test_with_organization_sets_label(self) -> None:
        org = Organization.objects.create(name="Test Org", color="#ff0000")
        ch = make_channel(telegram_id=1, title="Chan", organization=org)
        data = channel_network_data(ch)
        self.assertEqual(data["label"], "Chan")

    def test_communities_is_empty_dict_initially(self) -> None:
        ch = make_channel(telegram_id=1, title="Chan")
        data = channel_network_data(ch)
        self.assertEqual(data["communities"], {})

    def test_required_keys_present(self) -> None:
        ch = make_channel(telegram_id=1, title="Chan")
        data = channel_network_data(ch)
        for key in ("pk", "id", "label", "communities", "color", "url", "activity_period", "fans"):
            self.assertIn(key, data, msg=f"Missing key: {key}")

    def test_defaults_dict_merged(self) -> None:
        ch = make_channel(telegram_id=1, title="Chan")
        data = channel_network_data(ch, {"extra": "value"})
        self.assertEqual(data["extra"], "value")

    def test_defaults_override_computed_fields(self) -> None:
        ch = make_channel(telegram_id=1, title="Original")
        data = channel_network_data(ch, {"label": "Override"})
        self.assertEqual(data["label"], "Override")


# ─── Message model ─────────────────────────────────────────────────────────────


class MessageSaveTests(TestCase):
    def setUp(self) -> None:
        self.ch = make_channel(telegram_id=1, title="Ch")

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
        ch = make_channel(telegram_id=1, username="mychan")
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
        class OtherFake(self._Fake):
            id = 888

        obj = Channel.from_telegram_object(OtherFake(), defaults={"to_inspect": True})
        self.assertTrue(obj.to_inspect)


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
        self.ch = make_channel(telegram_id=1, title="Test Channel")
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
        other = make_channel(telegram_id=2, title="Other")
        Message.objects.create(telegram_id=99, channel=other)
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}))
        channel_ids = {m.channel_id for m in response.context["object_list"]}
        self.assertEqual(channel_ids, {self.ch.pk})

    def test_uses_digg_paginator(self) -> None:
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}))
        self.assertIsInstance(response.context["paginator"], DiggPaginator)

    def test_lost_excluded_by_default(self) -> None:
        Message.objects.create(telegram_id=42, channel=self.ch, is_lost=True)
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}))
        tids = {m.telegram_id for m in response.context["object_list"]}
        self.assertNotIn(42, tids)

    def test_lost_only_returns_lost(self) -> None:
        Message.objects.create(telegram_id=42, channel=self.ch, is_lost=True)
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}) + "?lost=only")
        tids = {m.telegram_id for m in response.context["object_list"]}
        self.assertEqual(tids, {42})

    def test_lost_include_returns_everything(self) -> None:
        Message.objects.create(telegram_id=42, channel=self.ch, is_lost=True)
        response = self.client.get(reverse("channel-detail", kwargs={"pk": self.ch.pk}) + "?lost=include")
        tids = {m.telegram_id for m in response.context["object_list"]}
        self.assertEqual(tids, {0, 1, 2, 42})


# ─── VacanciesView ─────────────────────────────────────────────────────────────


class VacanciesViewTests(TestCase):
    """The vacancies list reports the number of DISTINCT in-target channels that
    forwarded from the vacancy channel — regression for the subquery that used to
    return one arbitrary amplifier's message count (GROUP BY pk + LIMIT 1)."""

    def setUp(self) -> None:
        self.org = Organization.objects.create(name="Org", is_in_target=True)
        self.vacancy_ch = make_channel(telegram_id=1, organization=self.org, title="Vacancy")
        self.amp1 = make_channel(telegram_id=2, organization=self.org, title="Amp1")
        self.amp2 = make_channel(telegram_id=3, organization=self.org, title="Amp2")
        self.outsider = make_channel(telegram_id=4, title="Outsider")  # not in-target
        # amp1 forwards from the vacancy 3 times, amp2 once → 2 distinct amplifiers.
        for tid in (1, 2, 3):
            Message.objects.create(telegram_id=tid, channel=self.amp1, forwarded_from=self.vacancy_ch)
        Message.objects.create(telegram_id=1, channel=self.amp2, forwarded_from=self.vacancy_ch)
        # A non-in-target forwarder must not be counted.
        Message.objects.create(telegram_id=1, channel=self.outsider, forwarded_from=self.vacancy_ch)
        ChannelVacancy.objects.create(channel=self.vacancy_ch, closure_date=datetime.date(2024, 1, 1))

    def test_orphaned_amplifier_count_is_distinct_in_target_channels(self) -> None:
        response = self.client.get(reverse("channel-vacancies"))
        self.assertEqual(response.status_code, 200)
        rows = response.context["vacancies"]
        self.assertEqual(len(rows), 1)
        # 2 distinct amplifiers (amp1, amp2): not amp1's 3 messages, not amp2's 1,
        # not the 4 total forwards, and the non-in-target outsider is excluded.
        self.assertEqual(rows[0]["orphaned_amplifier_count"], 2)


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


# ---------------------------------------------------------------------------
# Album / grouped_id behaviour
# ---------------------------------------------------------------------------


class MessageAlbumTests(TestCase):
    """Tests for Telegram media-group (album) collapsing.

    Telegram emits each photo/video of an album as a separate Message with the
    same ``grouped_id``. The view layer hides every album member except the
    head, and the head exposes ``album_pictures`` etc. that span every sibling.
    """

    def setUp(self) -> None:
        from webapp.models import MessagePicture

        self.org = Organization.objects.create(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=10, organization=self.org)
        # Album of three messages sharing grouped_id=999
        self.head = Message.objects.create(telegram_id=100, channel=self.channel, grouped_id=999, message="caption")
        self.tail1 = Message.objects.create(telegram_id=101, channel=self.channel, grouped_id=999)
        self.tail2 = Message.objects.create(telegram_id=102, channel=self.channel, grouped_id=999)
        # Standalone message — no grouped_id
        self.standalone = Message.objects.create(telegram_id=200, channel=self.channel, grouped_id=None)
        # Attach one picture to each message so the album-wide gallery is testable
        for msg in (self.head, self.tail1, self.tail2, self.standalone):
            MessagePicture.objects.create(message=msg, telegram_id=msg.telegram_id, picture="x.jpg")

    def test_is_album_flag(self) -> None:
        self.assertTrue(self.head.is_album)
        self.assertTrue(self.tail1.is_album)
        self.assertFalse(self.standalone.is_album)

    def test_album_size(self) -> None:
        self.assertEqual(self.head.album_size, 3)
        self.assertEqual(self.tail1.album_size, 3)
        self.assertEqual(self.standalone.album_size, 1)

    def test_album_pictures_combines_siblings_for_head(self) -> None:
        pics = self.head.album_pictures
        # Head sees pictures from all three album members in telegram_id order
        self.assertEqual([p.message_id for p in pics], [self.head.id, self.tail1.id, self.tail2.id])

    def test_album_pictures_for_standalone_returns_only_self(self) -> None:
        self.assertEqual([p.message_id for p in self.standalone.album_pictures], [self.standalone.id])

    def test_exclude_album_tails_keeps_head_and_standalone_only(self) -> None:
        from django.http import QueryDict

        from webapp.views import _apply_message_options

        qs = Message.objects.filter(channel=self.channel)
        # lost=include keeps everything; default lost=exclude is the same here
        # since none of the messages are lost.
        params = QueryDict("lost=include")
        visible_ids = set(_apply_message_options(qs, params).values_list("id", flat=True))
        self.assertEqual(visible_ids, {self.head.id, self.standalone.id})

    def test_attach_album_data_avoids_n_plus_one(self) -> None:
        """Bulk-loading album media should issue 6 queries regardless of page size."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # A page-of-three (one album head + standalone): media access without
        # the bulk loader fires per-property queries; with it, those queries
        # are replaced by 6 batched fetches in attach_album_data itself.
        page = list(
            Message.objects.filter(channel=self.channel, grouped_id__isnull=False)
            .exclude(telegram_id__in=[self.tail1.telegram_id, self.tail2.telegram_id])
            .union(Message.objects.filter(pk=self.standalone.pk))
            .order_by("telegram_id")
        )
        self.assertEqual({m.pk for m in page}, {self.head.pk, self.standalone.pk})

        with CaptureQueriesContext(connection) as ctx:
            Message.attach_album_data(page)
            attach_queries = len(ctx.captured_queries)
            for msg in page:
                _ = msg.album_pictures
                _ = msg.album_videos
                _ = msg.album_audios
                _ = msg.album_stickers
                _ = msg.album_other_media
                _ = msg.album_size

        # attach_album_data does 1 sibling-Messages query + 5 media-model
        # queries (one per media type) = 6. Subsequent property access on
        # album messages reads the cache (0 queries); on non-album messages
        # it hits the prefetched related set (0 queries here because we
        # never prefetched, but Django still doesn't issue a count for
        # album_size since the message isn't an album).
        self.assertEqual(attach_queries, 6)
        # The standalone (non-album) message will issue one query per
        # media-set property since we didn't prefetch_related; the album
        # head's six property accesses are all cache hits.
        property_access_queries = len(ctx.captured_queries) - attach_queries
        self.assertLessEqual(property_access_queries, 5)  # at most one per media type for the standalone

    def test_attach_album_data_is_idempotent_when_no_albums(self) -> None:
        """No-op fast path when the page has zero album messages."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            Message.attach_album_data([self.standalone])
        self.assertEqual(len(ctx.captured_queries), 0)
        self.assertFalse(hasattr(self.standalone, "_album_cache"))


class AlbumMissingMediaTests(TestCase):
    """The gallery must show a placeholder per sibling whose media never
    downloaded — otherwise an album of 1 photo + 2 undownloaded videos
    visually renders as just the photo, dropping two items silently."""

    def setUp(self) -> None:
        from webapp.models import MessagePicture, MessageVideo

        self.org = Organization.objects.create(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=20, organization=self.org)
        # Album of 3 siblings: 1 photo (downloaded) + 2 videos (NOT downloaded).
        self.head = Message.objects.create(telegram_id=300, channel=self.channel, grouped_id=777, media_type="photo")
        self.video1 = Message.objects.create(telegram_id=301, channel=self.channel, grouped_id=777, media_type="video")
        self.video2 = Message.objects.create(telegram_id=302, channel=self.channel, grouped_id=777, media_type="video")
        MessagePicture.objects.create(message=self.head, telegram_id=300, picture="head.jpg")
        # Empty-file video row (e.g. crawled but file went missing) counts as missing too.
        MessageVideo.objects.create(message=self.video1, telegram_id=301, video="")

    def test_missing_videos_for_undownloaded_siblings(self) -> None:
        # Head sees its 1 picture (present) and 0 video files (both siblings missing).
        self.assertEqual(len(self.head.album_pictures), 1)
        self.assertEqual(len(self.head.album_videos), 1)  # video1 row exists with empty file
        self.assertEqual(self.head.album_missing_pictures, [])
        self.assertEqual(len(self.head.album_missing_videos), 2)  # video1 (empty file) + video2 (no row)

    def test_no_placeholders_when_everything_downloaded(self) -> None:
        from webapp.models import MessageVideo

        # Fill the empty file on video1 and add the missing row for video2.
        v1 = MessageVideo.objects.get(message=self.video1)
        v1.video = "v1.mp4"
        v1.save()
        MessageVideo.objects.create(message=self.video2, telegram_id=302, video="v2.mp4")
        self.assertEqual(self.head.album_missing_pictures, [])
        self.assertEqual(self.head.album_missing_videos, [])

    def test_missing_picture_on_standalone_post(self) -> None:
        """The placeholder logic also covers non-album messages."""
        lone = Message.objects.create(telegram_id=400, channel=self.channel, grouped_id=None, media_type="photo")
        # No MessagePicture row at all ⇒ one placeholder expected.
        self.assertEqual(len(lone.album_missing_pictures), 1)
        self.assertEqual(lone.album_missing_videos, [])

    def test_attach_album_data_caches_sibling_type_counts(self) -> None:
        """The bulk loader must populate `_album_sibling_type_counts` so the
        per-type placeholder properties don't re-query the database."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        Message.attach_album_data([self.head])
        with CaptureQueriesContext(connection) as ctx:
            _ = self.head.album_missing_pictures
            _ = self.head.album_missing_videos
            _ = self.head.album_missing_audios
            _ = self.head.album_missing_stickers
            _ = self.head.album_missing_other_media
        self.assertEqual(len(ctx.captured_queries), 0)


# ─── purge_out_of_target_messages ──────────────────────────────────────────────


class PurgeOutOfTargetTests(TestCase):
    """``purge_out_of_target_messages`` deletes the right rows and the right files."""

    def setUp(self) -> None:
        import tempfile

        from django.core.files.base import ContentFile
        from django.test import override_settings

        from webapp.models import MessagePicture

        # Sandbox MEDIA_ROOT to a temp dir — without this, ``self.pic.picture.save``
        # below lands in the real media tree (e.g. ``media/channels/5/message/200.jpg``)
        # and leaves a 15-byte ``fake-jpeg-bytes`` file behind on every test run.
        # Each subsequent run collides on the path and Django generates a suffix,
        # producing accumulating orphans like ``200_XxXxXxX.jpg``.
        self._media_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._media_tmp.cleanup)
        self._media_override = override_settings(MEDIA_ROOT=self._media_tmp.name)
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)

        # An in-target organisation; channels under it survive the purge.
        self.in_target_org = Organization.objects.create(name="Org-A", is_in_target=True)
        # Plain in-target channel — survives.
        self.healthy = make_channel(telegram_id=1, title="healthy", organization=self.in_target_org)
        # Marked in-target but currently lost — MUST survive (Bug 1).
        self.lost = make_channel(telegram_id=2, title="lost-chan", organization=self.in_target_org, is_lost=True)
        # Marked in-target but currently private — MUST survive (Bug 1).
        self.private = make_channel(
            telegram_id=3, title="private-chan", organization=self.in_target_org, is_private=True
        )
        # Marked in-target but a gigagroup (excluded by DEFAULT_CHANNEL_TYPES=CHANNEL) — MUST survive (Bug 1).
        self.giga = make_channel(telegram_id=4, title="giga-chan", organization=self.in_target_org, gigagroup=True)
        # Out-of-target organisation; channels under it get purged unless they're forward sources.
        self.out_org = Organization.objects.create(name="Org-B", is_in_target=False)
        self.purgeable = make_channel(telegram_id=5, title="purge-me", organization=self.out_org)
        # Forward source — out-of-target but referenced by an in-target message (Bug 2 fix).
        self.fwd_source = make_channel(telegram_id=6, title="fwd-source", organization=self.out_org)
        # Mention target — out-of-target, linked only via the references M2M.
        self.mention_target = make_channel(telegram_id=7, title="mention-target", organization=self.out_org)

        # Messages: each surviving channel gets one, plus the purgeable + fwd_source ones.
        Message.objects.create(telegram_id=100, channel=self.healthy)
        Message.objects.create(telegram_id=101, channel=self.lost)
        Message.objects.create(telegram_id=102, channel=self.private)
        Message.objects.create(telegram_id=103, channel=self.giga)
        self.purge_msg = Message.objects.create(telegram_id=200, channel=self.purgeable)
        self.fwd_msg = Message.objects.create(telegram_id=201, channel=self.fwd_source)
        self.mention_msg = Message.objects.create(telegram_id=202, channel=self.mention_target)

        # The healthy in-target channel has a message that forwards-from fwd_source.
        Message.objects.create(telegram_id=104, channel=self.healthy, forwarded_from=self.fwd_source)
        # And another in-target message that *mentions* mention_target via references M2M.
        mention_in_target = Message.objects.create(telegram_id=105, channel=self.healthy)
        mention_in_target.references.add(self.mention_target)

        # Attach one picture to the purgeable message so we can assert the file
        # is unlinked from disk (and not just from the DB).
        self.pic = MessagePicture.objects.create(message=self.purge_msg, telegram_id=999)
        self.pic.picture.save("purgeable.jpg", ContentFile(b"fake-jpeg-bytes"), save=True)

    def _run_purge(self, **kwargs):
        from webapp.management.commands.purge_out_of_target_messages import purge

        return purge(**kwargs)

    def test_dry_run_changes_nothing(self) -> None:
        before = Message.objects.count()
        report = self._run_purge(dry_run=True)
        self.assertEqual(Message.objects.count(), before)
        self.assertEqual(report.candidate_messages, 2)  # purge_msg + mention_msg
        self.assertEqual(report.candidate_media_files, 1)
        self.assertEqual(report.deleted_messages, 0)

    def test_marked_in_target_kept_even_when_lost_or_private_or_wrong_type(self) -> None:
        """Bug 1 fix: lost/private/wrong-type channels still keep their messages."""
        self._run_purge()
        for ch in (self.healthy, self.lost, self.private, self.giga):
            self.assertTrue(
                Message.objects.filter(channel=ch).exists(),
                f"channel {ch.title} lost its messages despite being marked in-target",
            )

    def test_forward_source_messages_kept(self) -> None:
        """Bug 2 fix: forward-source channel survives because in-target msgs forward from it."""
        self._run_purge()
        self.assertTrue(Message.objects.filter(pk=self.fwd_msg.pk).exists())

    def test_purgeable_channel_messages_deleted(self) -> None:
        self._run_purge()
        self.assertFalse(Message.objects.filter(pk=self.purge_msg.pk).exists())

    def test_shared_media_file_kept_when_referenced_by_surviving_message(self) -> None:
        """A file shared (same Telegram file id ⇒ same path) by a purged out-of-target
        message and a kept in-target message must survive — only its purged row goes."""
        import os

        from django.core.files.base import ContentFile

        from webapp.models import MessagePicture

        # Same telegram_id ⇒ both rows resolve to the same on-disk path (photos/888.jpg).
        kept_msg = Message.objects.create(telegram_id=300, channel=self.healthy)
        kept_pic = MessagePicture.objects.create(message=kept_msg, telegram_id=888)
        kept_pic.picture.save("shared.jpg", ContentFile(b"shared-bytes"), save=True)
        shared_path = kept_pic.picture.path
        purged_pic = MessagePicture.objects.create(message=self.purge_msg, telegram_id=888)
        purged_pic.picture.save("shared.jpg", ContentFile(b"shared-bytes"), save=True)
        self.assertEqual(kept_pic.picture.name, purged_pic.picture.name)  # same shared path

        self._run_purge()

        self.assertFalse(MessagePicture.objects.filter(pk=purged_pic.pk).exists())  # purged row gone
        self.assertTrue(MessagePicture.objects.filter(pk=kept_pic.pk).exists())  # kept row stays
        self.assertTrue(os.path.exists(shared_path), "shared media file was deleted out from under a surviving message")

    def test_mention_only_target_messages_deleted(self) -> None:
        """Channels reached only via t.me/ mentions don't shield their messages from the purge.

        The Channel row itself stays (it's used as a dead-leaf node in structural analysis);
        only its crawled messages go.
        """
        self._run_purge()
        self.assertFalse(Message.objects.filter(pk=self.mention_msg.pk).exists())
        # The Channel itself survives — it's still referenceable for analysis.
        self.assertTrue(Channel.objects.filter(pk=self.mention_target.pk).exists())

    def test_media_file_removed_from_disk(self) -> None:
        """Bug 3 fix: the actual .jpg file gets unlinked, not just the DB row."""
        import os

        # ``self.pic.picture`` was saved in setUp using whatever MEDIA_ROOT was
        # active then; the path is absolute so we can re-check it here.
        path = self.pic.picture.path
        self.assertTrue(os.path.exists(path), "test setup did not create the file")
        try:
            report = self._run_purge()
            self.assertEqual(report.removed_files, 1)
            self.assertFalse(os.path.exists(path))
        finally:
            # Belt-and-braces: if the purge failed mid-test, clean up the orphan.
            if os.path.exists(path):
                os.unlink(path)

    def test_refuses_when_no_in_target_channels(self) -> None:
        """Refuse to delete every message when no channel is marked in-target."""
        from django.core.management.base import CommandError

        self.in_target_org.is_in_target = False
        self.in_target_org.save()
        Channel.objects.update(to_inspect=False)
        with self.assertRaises(CommandError):
            self._run_purge()
        # Nothing was touched.
        self.assertGreater(Message.objects.count(), 0)

    def test_to_inspect_protects_channel(self) -> None:
        """A channel under a non-in-target org but with to_inspect=True keeps its crawled messages."""
        ch = make_channel(telegram_id=999, title="inspect-protected", organization=self.out_org, to_inspect=True)
        msg = Message.objects.create(telegram_id=900, channel=ch)
        self._run_purge()
        self.assertTrue(Message.objects.filter(pk=msg.pk).exists())


# ─── purge_orphan_media ────────────────────────────────────────────────────────


class PurgeOrphanMediaTests(TestCase):
    """``purge_orphan_media`` removes only un-referenced files under media/channels."""

    def _make_layout(self, media_root: str):
        """Plant one referenced file + one orphan + one out-of-scope file."""
        import os
        from pathlib import Path

        from django.core.files.base import ContentFile

        from webapp.models import MessagePicture

        self.org = Organization.objects.create(name="Org", is_in_target=True)
        self.channel = make_channel(telegram_id=1, organization=self.org, username="ch")
        msg = Message.objects.create(telegram_id=1, channel=self.channel)
        pic = MessagePicture.objects.create(message=msg, telegram_id=1)
        pic.picture.save("kept.jpg", ContentFile(b"referenced bytes"), save=True)
        self.referenced_path = Path(pic.picture.path)

        # Orphan inside channels/ (target of cleanup).
        channels_dir = Path(media_root) / "channels"
        orphan_dir = channels_dir / "ch" / "message"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        self.orphan_path = orphan_dir / "orphan.jpg"
        self.orphan_path.write_bytes(b"orphan bytes")

        # Empty-on-cleanup directory: an isolated subdir under channels/ that will be empty
        # once we delete its only file.
        empty_parent = channels_dir / "abandoned" / "message"
        empty_parent.mkdir(parents=True, exist_ok=True)
        self.empty_parent_orphan = empty_parent / "lone.jpg"
        self.empty_parent_orphan.write_bytes(b"lone")
        self.empty_parent = empty_parent

        # Out-of-scope file: lives directly under MEDIA_ROOT (not under channels/),
        # so the cleanup must not touch it.
        outside = Path(media_root) / "exports"
        outside.mkdir(parents=True, exist_ok=True)
        self.outside_path = outside / "user-managed.txt"
        self.outside_path.write_bytes(b"do not touch")

        # Symlink pointing at the referenced file: the cleanup must skip symlinks.
        if hasattr(os, "symlink"):
            self.symlink_path = channels_dir / "ch" / "message" / "link.jpg"
            try:
                self.symlink_path.symlink_to(self.referenced_path)
            except OSError:
                self.symlink_path = None
        else:
            self.symlink_path = None

    def test_dry_run_reports_orphans_without_deleting(self) -> None:
        import tempfile

        from django.test import override_settings

        from webapp.management.commands.purge_orphan_media import purge_orphans

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._make_layout(media_root)
            report = purge_orphans(dry_run=True)
            self.assertEqual(report.candidate_files, 2)  # orphan + empty_parent_orphan
            self.assertGreater(report.candidate_bytes, 0)
            self.assertEqual(report.removed_files, 0)
            self.assertTrue(self.orphan_path.exists())  # not actually deleted
            self.assertTrue(self.referenced_path.exists())

    def test_run_deletes_orphans_only(self) -> None:
        import tempfile

        from django.test import override_settings

        from webapp.management.commands.purge_orphan_media import purge_orphans

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._make_layout(media_root)
            report = purge_orphans(dry_run=False)
            self.assertEqual(report.removed_files, 2)
            self.assertGreater(report.removed_bytes, 0)
            # Orphans gone, referenced file preserved.
            self.assertFalse(self.orphan_path.exists())
            self.assertFalse(self.empty_parent_orphan.exists())
            self.assertTrue(self.referenced_path.exists())
            # Out-of-scope path is untouched.
            self.assertTrue(self.outside_path.exists())
            # Empty subdirectory was tidied up.
            self.assertFalse(self.empty_parent.exists())

    def test_symlinks_are_skipped(self) -> None:
        import tempfile

        from django.test import override_settings

        from webapp.management.commands.purge_orphan_media import purge_orphans

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._make_layout(media_root)
            if self.symlink_path is None:
                self.skipTest("symlinks unavailable on this platform")
            self.assertTrue(self.symlink_path.is_symlink())
            purge_orphans(dry_run=False)
            # The symlink survives (we never unlink the link itself).
            self.assertTrue(self.symlink_path.is_symlink())

    def test_missing_channels_root_returns_empty_report(self) -> None:
        import tempfile

        from django.test import override_settings

        from webapp.management.commands.purge_orphan_media import purge_orphans

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            # MEDIA_ROOT exists but channels/ does not — the cleanup is a no-op.
            report = purge_orphans(dry_run=True)
            self.assertEqual(report.candidate_files, 0)
            self.assertEqual(report.candidate_bytes, 0)


class ScoreMessagesTests(TestCase):
    """Pure scoring core: deterministic, no DB writes, partial renormalisation."""

    def test_empty_input_returns_empty_dict(self) -> None:
        from webapp.scoring import score_messages

        self.assertEqual(score_messages([]), {})

    def test_below_min_sample_yields_null_scores(self) -> None:
        from webapp.scoring import score_messages

        rows = [(i, 100 + i, 5, 2) for i in range(5)]
        scored = score_messages(rows, min_sample=10)
        self.assertEqual(len(scored), 5)
        for pk, (zv, zf, zr, interest) in scored.items():
            self.assertIsNone(zv, msg=f"pk={pk}")
            self.assertIsNone(zf)
            self.assertIsNone(zr)
            self.assertIsNone(interest)

    def test_z_scores_have_zero_mean_unit_std(self) -> None:
        from webapp.scoring import score_messages

        rows = [(i, 10 * i + 50, 5, 3) for i in range(50)]
        scored = score_messages(rows, min_sample=10)
        zv_values = [t[0] for t in scored.values() if t[0] is not None]
        self.assertEqual(len(zv_values), 50)
        self.assertAlmostEqual(sum(zv_values) / len(zv_values), 0.0, places=6)
        variance = sum(z * z for z in zv_values) / len(zv_values)
        self.assertAlmostEqual(variance, 1.0, places=6)

    def test_partial_renormalisation_when_one_facet_is_constant(self) -> None:
        from webapp.scoring import score_messages

        # forwards is constant => stddev=0 => that facet is skipped; interest
        # composite still produced from views + reactions on rescaled weights.
        rows = [(i, 100 + i, 5, 10 + i) for i in range(40)]
        scored = score_messages(rows, min_sample=10)
        for _pk, (zv, zf, zr, interest) in scored.items():
            self.assertIsNotNone(zv)
            self.assertIsNone(zf, msg="constant facet should be dropped")
            self.assertIsNotNone(zr)
            self.assertIsNotNone(interest)

    def test_recompute_channel_matches_pure_score(self) -> None:
        """recompute_channel must produce the same interest_score as the pure
        score_messages call it now delegates to — guards the refactor."""
        from webapp.scoring import recompute_channel, score_messages

        org = Organization.objects.create(name="In target", is_in_target=True)
        ch = make_channel(telegram_id=2001, title="ScoringCh", organization=org)
        base = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        for i in range(40):
            Message.objects.create(
                telegram_id=10_000 + i,
                channel=ch,
                date=base + datetime.timedelta(days=i),
                views=100 + i,
                forwards=5 + (i % 4),
                total_reactions=2 + (i % 3),
            )
        rows = list(
            Message.objects.alive().filter(channel_id=ch.pk).values_list("pk", "views", "forwards", "total_reactions")
        )
        expected = score_messages(rows)
        n = recompute_channel(ch.pk)
        self.assertEqual(n, 40)
        for msg in Message.objects.filter(channel_id=ch.pk):
            _zv, _zf, _zr, expected_score = expected[msg.pk]
            if expected_score is None:
                self.assertIsNone(msg.interest_score)
            else:
                self.assertAlmostEqual(msg.interest_score, expected_score, places=6)


class ScoreMessagesForWindowTests(TestCase):
    """The export-facing wrapper groups by channel and keys by (channel, telegram_id)."""

    def test_keys_are_channel_telegram_pairs(self) -> None:
        from webapp.scoring import score_messages_for_window

        org = Organization.objects.create(name="In target", is_in_target=True)
        ch1 = make_channel(telegram_id=3001, title="A", organization=org)
        ch2 = make_channel(telegram_id=3002, title="B", organization=org)
        base = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)
        for i in range(40):
            Message.objects.create(
                telegram_id=20_000 + i,
                channel=ch1,
                date=base + datetime.timedelta(days=i),
                views=50 + i,
                forwards=2,
                total_reactions=1,
            )
        for i in range(40):
            Message.objects.create(
                telegram_id=30_000 + i,
                channel=ch2,
                date=base + datetime.timedelta(days=i),
                views=200 + 2 * i,
                forwards=10,
                total_reactions=5,
            )

        score_map = score_messages_for_window(Message.objects.alive())
        keys = list(score_map.keys())
        # Every key is a (channel_pk, telegram_id) pair; both channels represented.
        self.assertTrue(all(isinstance(k, tuple) and len(k) == 2 for k in keys))
        self.assertTrue(any(k[0] == ch1.pk for k in keys))
        self.assertTrue(any(k[0] == ch2.pk for k in keys))

    def test_window_filter_restricts_to_subset(self) -> None:
        """Filtering the queryset before calling restricts both the baseline AND
        which messages get scored — narrow windows produce smaller maps."""
        from webapp.scoring import score_messages_for_window

        org = Organization.objects.create(name="In target", is_in_target=True)
        ch = make_channel(telegram_id=3003, title="C", organization=org)
        base = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        for i in range(40):
            Message.objects.create(
                telegram_id=40_000 + i,
                channel=ch,
                date=base + datetime.timedelta(days=i),
                views=50 + i,
                forwards=2,
                total_reactions=1,
            )

        cutoff = base + datetime.timedelta(days=20)
        narrow = score_messages_for_window(Message.objects.alive().filter(date__lt=cutoff), min_sample=10)
        full = score_messages_for_window(Message.objects.alive(), min_sample=10)
        self.assertLess(len(narrow), len(full))


class ChannelAttributionModelTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="O", is_in_target=True)
        self.ch = make_channel(telegram_id=1)

    def test_overlap_rejected(self) -> None:
        attribute(self.ch, self.org, datetime.date(2024, 1, 1), datetime.date(2024, 6, 30))
        # end=X and a sibling start=X overlap (inclusive bounds).
        dup = ChannelAttribution(channel=self.ch, organization=self.org, start=datetime.date(2024, 6, 30), end=None)
        with self.assertRaises(ValidationError):
            dup.clean()

    def test_open_periods_overlap_rejected(self) -> None:
        attribute(self.ch, self.org, None, None)
        dup = ChannelAttribution(channel=self.ch, organization=self.org, start=datetime.date(2030, 1, 1), end=None)
        with self.assertRaises(ValidationError):
            dup.clean()

    def test_adjacent_periods_allowed(self) -> None:
        attribute(self.ch, self.org, datetime.date(2024, 1, 1), datetime.date(2024, 6, 30))
        nxt = ChannelAttribution(channel=self.ch, organization=self.org, start=datetime.date(2024, 7, 1), end=None)
        nxt.clean()  # adjacent (start = end + 1 day) does not overlap

    def test_end_before_start_rejected(self) -> None:
        bad = ChannelAttribution(
            channel=self.ch, organization=self.org, start=datetime.date(2024, 6, 1), end=datetime.date(2024, 1, 1)
        )
        with self.assertRaises(ValidationError):
            bad.clean()


class CurrentOrganizationTests(TestCase):
    def setUp(self) -> None:
        self.org_a = Organization.objects.create(name="A", is_in_target=True)
        self.org_b = Organization.objects.create(name="B", is_in_target=True)

    def test_active_today_wins_over_past(self) -> None:
        ch = make_channel(telegram_id=1)
        attribute(ch, self.org_a, datetime.date(2020, 1, 1), datetime.date(2021, 1, 1))
        attribute(ch, self.org_b, datetime.date(2024, 1, 1), None)
        self.assertEqual(ch.current_organization, self.org_b)

    def test_most_recent_past_when_none_active(self) -> None:
        ch = make_channel(telegram_id=2)
        attribute(ch, self.org_a, datetime.date(2018, 1, 1), datetime.date(2019, 1, 1))
        attribute(ch, self.org_b, datetime.date(2020, 1, 1), datetime.date(2021, 1, 1))
        self.assertEqual(ch.current_organization, self.org_b)

    def test_none_when_unattributed(self) -> None:
        self.assertIsNone(make_channel(telegram_id=3).current_organization)


class InTargetPeriodQuerysetTests(TestCase):
    def test_past_in_target_period_qualifies(self) -> None:
        org = Organization.objects.create(name="O", is_in_target=True)
        ch = make_channel(
            telegram_id=1,
            organization=org,
            attribution_start=datetime.date(2020, 1, 1),
            attribution_end=datetime.date(2020, 6, 1),
        )
        self.assertIn(ch, Channel.objects.in_target())

    def test_out_of_target_org_excluded(self) -> None:
        org = Organization.objects.create(name="O", is_in_target=False)
        ch = make_channel(telegram_id=2, organization=org)
        self.assertNotIn(ch, Channel.objects.in_target())

    def test_unattributed_excluded(self) -> None:
        self.assertNotIn(make_channel(telegram_id=3), Channel.objects.in_target())


class PurgeOutOfPeriodTests(TestCase):
    def _purgeable_ids(self) -> set[int]:
        from webapp.management.commands.purge_out_of_target_messages import find_purgeable_messages

        return set(find_purgeable_messages().values_list("telegram_id", flat=True))

    def _msg(self, channel, tid, year, month) -> None:
        Message.objects.create(
            telegram_id=tid,
            channel=channel,
            date=datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc),
        )

    def test_out_of_period_pruned_for_kept_channel(self) -> None:
        org = Organization.objects.create(name="O", is_in_target=True)
        ch = make_channel(
            telegram_id=1,
            organization=org,
            attribution_start=datetime.date(2024, 1, 1),
            attribution_end=datetime.date(2024, 3, 31),
        )
        self._msg(ch, 1, 2024, 2)  # in period
        self._msg(ch, 2, 2024, 6)  # out of period
        purgeable = self._purgeable_ids()
        self.assertIn(2, purgeable)
        self.assertNotIn(1, purgeable)

    def test_to_inspect_keeps_all(self) -> None:
        ch = make_channel(telegram_id=5, to_inspect=True)
        self._msg(ch, 50, 2024, 6)
        self.assertNotIn(50, self._purgeable_ids())
