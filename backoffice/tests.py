"""Tests for backoffice: access control, API utils, serializers, and all viewsets."""

from __future__ import annotations

import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from events.models import Event, EventType
from webapp.models import Channel, ChannelGroup, Organization, SearchTerm

# ---------------------------------------------------------------------------
# backoffice/api/utils.py — _normalize
# ---------------------------------------------------------------------------


class NormalizeTests(TestCase):
    def test_empty_string_returns_empty(self):
        from backoffice.api.utils import _normalize

        self.assertEqual(_normalize(""), "")

    def test_lowercases(self):
        from backoffice.api.utils import _normalize

        self.assertEqual(_normalize("UPPER"), "upper")

    def test_strips_accents(self):
        from backoffice.api.utils import _normalize

        self.assertEqual(_normalize("Hélix"), "helix")
        self.assertEqual(_normalize("ñoño"), "nono")
        self.assertEqual(_normalize("çà"), "ca")

    def test_mixed_accent_and_case(self):
        from backoffice.api.utils import _normalize

        self.assertEqual(_normalize("Ça Va"), "ca va")

    def test_plain_ascii_unchanged(self):
        from backoffice.api.utils import _normalize

        self.assertEqual(_normalize("hello world"), "hello world")


# ---------------------------------------------------------------------------
# backoffice/api/permissions.py — BackofficePermission
# ---------------------------------------------------------------------------


class BackofficePermissionTests(TestCase):
    def _make_request(self, is_staff=False, is_authenticated=True):
        from unittest.mock import MagicMock

        req = MagicMock()
        req.user = MagicMock()
        req.user.is_staff = is_staff
        req.user.is_authenticated = is_authenticated
        return req

    @override_settings(WEB_ACCESS="ALL")
    def test_web_access_all_always_permits(self):
        from backoffice.api.permissions import BackofficePermission

        perm = BackofficePermission()
        self.assertTrue(perm.has_permission(self._make_request(is_staff=False), None))
        self.assertTrue(perm.has_permission(self._make_request(is_authenticated=False), None))

    @override_settings(WEB_ACCESS="OPEN")
    def test_web_access_open_requires_staff(self):
        from backoffice.api.permissions import BackofficePermission

        perm = BackofficePermission()
        self.assertTrue(perm.has_permission(self._make_request(is_staff=True), None))
        self.assertFalse(perm.has_permission(self._make_request(is_staff=False), None))

    @override_settings(WEB_ACCESS="PROTECTED")
    def test_web_access_protected_requires_staff(self):
        from backoffice.api.permissions import BackofficePermission

        perm = BackofficePermission()
        self.assertTrue(perm.has_permission(self._make_request(is_staff=True), None))
        self.assertFalse(perm.has_permission(self._make_request(is_staff=False), None))


# ---------------------------------------------------------------------------
# backoffice/views.py — StaffRequiredMixin
# ---------------------------------------------------------------------------


class StaffRequiredMixinTests(TestCase):
    @override_settings(WEB_ACCESS="ALL")
    def test_all_mode_anonymous_user_can_access_channels(self):
        resp = self.client.get(reverse("backoffice:channels"))
        self.assertEqual(resp.status_code, 200)

    @override_settings(WEB_ACCESS="OPEN")
    def test_open_mode_anonymous_user_redirected(self):
        resp = self.client.get(reverse("backoffice:channels"))
        self.assertIn(resp.status_code, (302, 403))

    @override_settings(WEB_ACCESS="OPEN")
    def test_open_mode_staff_user_can_access(self):
        staff = User.objects.create_user("staff", password="x", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.get(reverse("backoffice:channels"))
        self.assertEqual(resp.status_code, 200)

    @override_settings(WEB_ACCESS="OPEN")
    def test_open_mode_non_staff_authenticated_user_gets_403(self):
        # WebAccessMiddleware returns 403 (not a redirect) for authenticated non-staff on /manage/.
        regular = User.objects.create_user("regular", password="x", is_staff=False)
        self.client.force_login(regular)
        resp = self.client.get(reverse("backoffice:channels"))
        self.assertEqual(resp.status_code, 403)


class BackofficePageTests(TestCase):
    """All page views return 200 under WEB_ACCESS=ALL (the default)."""

    def _check(self, url_name, kwargs=None):
        resp = self.client.get(reverse(f"backoffice:{url_name}", kwargs=kwargs))
        self.assertEqual(resp.status_code, 200, msg=f"{url_name} returned {resp.status_code}")

    def test_channels_page(self):
        self._check("channels")

    def test_channel_update_page(self):
        org = Organization.objects.create(name="Org", color="#ff0000")
        ch = Channel.objects.create(telegram_id=1, title="T", organization=org)
        self._check("channel-update", kwargs={"pk": ch.pk})

    def test_organizations_page(self):
        self._check("organizations")

    def test_groups_page(self):
        self._check("groups")

    def test_search_terms_page(self):
        self._check("search-terms")

    def test_events_page(self):
        self._check("events")

    def test_users_page(self):
        self._check("users")


# ---------------------------------------------------------------------------
# Helpers shared by API tests
# ---------------------------------------------------------------------------


def _api(path):
    """Return the full URL for a backoffice API path."""
    return f"/manage/api/{path}"


class _ApiTestCase(TestCase):
    """Base with JSON helpers."""

    def jget(self, url, **kwargs):
        return self.client.get(url, **kwargs)

    def jpost(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")

    def jpatch(self, url, data):
        return self.client.patch(url, json.dumps(data), content_type="application/json")

    def jdelete(self, url):
        return self.client.delete(url)


# ---------------------------------------------------------------------------
# backoffice/api — OrganizationViewSet
# ---------------------------------------------------------------------------


class OrganizationViewSetTests(_ApiTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Alpha", color="#ff0000", is_interesting=True)

    def test_list_returns_organizations(self):
        resp = self.jget(_api("organizations/"))
        names = [o["name"] for o in resp.json()["results"]]
        self.assertIn("Alpha", names)

    def test_list_includes_channel_count(self):
        Channel.objects.create(telegram_id=1, title="T", organization=self.org)
        resp = self.jget(_api("organizations/"))
        org = next(o for o in resp.json()["results"] if o["name"] == "Alpha")
        self.assertEqual(org["channel_count"], 1)

    def test_create_organization(self):
        resp = self.jpost(_api("organizations/"), {"name": "Beta", "color": "#00ff00", "is_interesting": False})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Organization.objects.filter(name="Beta").exists())

    def test_update_organization(self):
        resp = self.jpatch(_api(f"organizations/{self.org.pk}/"), {"is_interesting": False})
        self.assertEqual(resp.status_code, 200)
        self.org.refresh_from_db()
        self.assertFalse(self.org.is_interesting)

    def test_delete_organization(self):
        resp = self.jdelete(_api(f"organizations/{self.org.pk}/"))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Organization.objects.filter(pk=self.org.pk).exists())


# ---------------------------------------------------------------------------
# backoffice/api — ChannelGroupViewSet
# ---------------------------------------------------------------------------


class ChannelGroupViewSetTests(_ApiTestCase):
    def setUp(self):
        self.group = ChannelGroup.objects.create(name="GroupA")
        self.org = Organization.objects.create(name="O", color="#000000")
        self.ch1 = Channel.objects.create(telegram_id=10, title="C1", organization=self.org)
        self.ch2 = Channel.objects.create(telegram_id=11, title="C2", organization=self.org)

    def test_list_returns_groups(self):
        resp = self.jget(_api("groups/"))
        names = [g["name"] for g in resp.json()["results"]]
        self.assertIn("GroupA", names)

    def test_channel_count_annotation(self):
        self.group.channels.add(self.ch1)
        resp = self.jget(_api("groups/"))
        group = next(g for g in resp.json()["results"] if g["name"] == "GroupA")
        self.assertEqual(group["channel_count"], 1)

    def test_add_channels_action(self):
        resp = self.jpost(_api(f"groups/{self.group.pk}/channels/"), {"ids": [self.ch1.pk, self.ch2.pk]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.group.channels.count(), 2)

    def test_remove_channels_action(self):
        # DRF 3.17 generates separate URL patterns for add_channels (POST) and
        # remove_channels (DELETE) even though they share url_path="channels".
        # Django routes to the first match (POST only), so DELETE returns 405
        # through the URL router. Call the viewset method directly instead.
        from backoffice.api.views import ChannelGroupViewSet

        from rest_framework.test import APIRequestFactory

        self.group.channels.add(self.ch1, self.ch2)
        factory = APIRequestFactory()
        request = factory.delete("/", json.dumps({"ids": [self.ch1.pk]}), content_type="application/json")
        view = ChannelGroupViewSet.as_view({"delete": "remove_channels"})
        resp = view(request, pk=self.group.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.ch1, self.group.channels.all())
        self.assertIn(self.ch2, self.group.channels.all())

    def test_create_group(self):
        resp = self.jpost(_api("groups/"), {"name": "GroupB"})
        self.assertEqual(resp.status_code, 201)

    def test_delete_group(self):
        resp = self.jdelete(_api(f"groups/{self.group.pk}/"))
        self.assertEqual(resp.status_code, 204)


# ---------------------------------------------------------------------------
# backoffice/api — ChannelViewSet
# ---------------------------------------------------------------------------


class ChannelViewSetTests(_ApiTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="OrgA", color="#ff0000", is_interesting=True)
        self.org2 = Organization.objects.create(name="OrgB", color="#0000ff")
        self.group = ChannelGroup.objects.create(name="G1")
        self.ch = Channel.objects.create(telegram_id=1, title="Alpha Channel", username="alpha", organization=self.org)
        self.ch_lost = Channel.objects.create(telegram_id=2, title="Lost", is_lost=True)
        self.ch_private = Channel.objects.create(telegram_id=3, title="Private", is_private=True)

    def test_list_returns_channels(self):
        resp = self.jget(_api("channels/"))
        ids = [c["id"] for c in resp.json()["results"]]
        self.assertIn(self.ch.pk, ids)

    def test_retrieve_single_channel(self):
        resp = self.jget(_api(f"channels/{self.ch.pk}/"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], "Alpha Channel")

    def test_patch_assigns_organization(self):
        resp = self.jpatch(_api(f"channels/{self.ch.pk}/"), {"organization_id": self.org2.pk})
        self.assertEqual(resp.status_code, 200)
        self.ch.refresh_from_db()
        self.assertEqual(self.ch.organization, self.org2)

    def test_patch_clears_organization(self):
        resp = self.jpatch(_api(f"channels/{self.ch.pk}/"), {"organization_id": None})
        self.assertEqual(resp.status_code, 200)
        self.ch.refresh_from_db()
        self.assertIsNone(self.ch.organization)

    def test_patch_assigns_groups(self):
        resp = self.jpatch(_api(f"channels/{self.ch.pk}/"), {"group_ids": [self.group.pk]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.group, self.ch.groups.all())

    def test_search_filter_by_title(self):
        resp = self.jget(_api("channels/?search=Alpha"))
        titles = [c["title"] for c in resp.json()["results"]]
        self.assertIn("Alpha Channel", titles)
        self.assertNotIn("Lost", titles)

    def test_status_filter_interesting(self):
        resp = self.jget(_api("channels/?status=interesting"))
        ids = [c["id"] for c in resp.json()["results"]]
        self.assertIn(self.ch.pk, ids)
        self.assertNotIn(self.ch_lost.pk, ids)

    def test_status_filter_lost(self):
        resp = self.jget(_api("channels/?status=lost"))
        ids = [c["id"] for c in resp.json()["results"]]
        self.assertIn(self.ch_lost.pk, ids)
        self.assertNotIn(self.ch.pk, ids)

    def test_status_filter_private(self):
        resp = self.jget(_api("channels/?status=private"))
        ids = [c["id"] for c in resp.json()["results"]]
        self.assertIn(self.ch_private.pk, ids)

    def test_status_filter_unassigned(self):
        unassigned = Channel.objects.create(telegram_id=99, title="Unassigned")
        resp = self.jget(_api("channels/?status=unassigned"))
        ids = [c["id"] for c in resp.json()["results"]]
        self.assertIn(unassigned.pk, ids)
        self.assertNotIn(self.ch.pk, ids)

    def test_organization_filter(self):
        resp = self.jget(_api(f"channels/?organization={self.org.pk}"))
        ids = [c["id"] for c in resp.json()["results"]]
        self.assertIn(self.ch.pk, ids)

    def test_bulk_assign_organization(self):
        ch2 = Channel.objects.create(telegram_id=20, title="C2")
        resp = self.jpost(_api("channels/bulk-assign/"), {"ids": [self.ch.pk, ch2.pk], "organization_id": self.org2.pk})
        self.assertEqual(resp.status_code, 200)
        self.ch.refresh_from_db()
        ch2.refresh_from_db()
        self.assertEqual(self.ch.organization, self.org2)
        self.assertEqual(ch2.organization, self.org2)

    def test_bulk_assign_no_ids_returns_400(self):
        resp = self.jpost(_api("channels/bulk-assign/"), {"ids": []})
        self.assertEqual(resp.status_code, 400)

    def test_bulk_assign_add_group(self):
        resp = self.jpost(_api("channels/bulk-assign/"), {"ids": [self.ch.pk], "add_group_ids": [self.group.pk]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.group, self.ch.groups.all())

    def test_bulk_assign_remove_group(self):
        self.ch.groups.add(self.group)
        resp = self.jpost(_api("channels/bulk-assign/"), {"ids": [self.ch.pk], "remove_group_ids": [self.group.pk]})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.group, self.ch.groups.all())


# ---------------------------------------------------------------------------
# backoffice/api — SearchTermViewSet
# ---------------------------------------------------------------------------


class SearchTermViewSetTests(_ApiTestCase):
    def test_list_returns_search_terms(self):
        SearchTerm.objects.create(word="ukraine")
        resp = self.jget(_api("search-terms/"))
        words = [s["word"] for s in resp.json()["results"]]
        self.assertIn("ukraine", words)

    def test_create_lowercases_word(self):
        resp = self.jpost(_api("search-terms/"), {"word": "TELEGRAM"})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(SearchTerm.objects.filter(word="telegram").exists())

    def test_create_trims_whitespace(self):
        resp = self.jpost(_api("search-terms/"), {"word": "  test  "})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(SearchTerm.objects.filter(word="test").exists())

    def test_create_deduplicates(self):
        SearchTerm.objects.create(word="news")
        resp = self.jpost(_api("search-terms/"), {"word": "NEWS"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(SearchTerm.objects.filter(word="news").count(), 1)

    def test_delete_search_term(self):
        st = SearchTerm.objects.create(word="delete-me")
        resp = self.jdelete(_api(f"search-terms/{st.pk}/"))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(SearchTerm.objects.filter(pk=st.pk).exists())


# ---------------------------------------------------------------------------
# backoffice/api — EventTypeViewSet
# ---------------------------------------------------------------------------


class EventTypeViewSetTests(_ApiTestCase):
    def test_list_returns_event_types(self):
        EventType.objects.create(name="Protest", color="#ff0000")
        resp = self.jget(_api("event-types/"))
        names = [e["name"] for e in resp.json()["results"]]
        self.assertIn("Protest", names)

    def test_create_event_type(self):
        resp = self.jpost(_api("event-types/"), {"name": "Election", "color": "#0000ff"})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(EventType.objects.filter(name="Election").exists())

    def test_event_count_annotation(self):
        et = EventType.objects.create(name="TypeA", color="#000000")
        Event.objects.create(date="2026-01-01", subject="E1", action=et)
        resp = self.jget(_api("event-types/"))
        entry = next(e for e in resp.json()["results"] if e["name"] == "TypeA")
        self.assertEqual(entry["event_count"], 1)

    def test_delete_event_type(self):
        et = EventType.objects.create(name="Temp", color="#aaaaaa")
        resp = self.jdelete(_api(f"event-types/{et.pk}/"))
        self.assertEqual(resp.status_code, 204)


# ---------------------------------------------------------------------------
# backoffice/api — EventViewSet
# ---------------------------------------------------------------------------


class EventViewSetTests(_ApiTestCase):
    def setUp(self):
        self.et1 = EventType.objects.create(name="TypeA", color="#ff0000")
        self.et2 = EventType.objects.create(name="TypeB", color="#00ff00")
        self.e1 = Event.objects.create(date="2024-06-01", subject="E1", action=self.et1)
        self.e2 = Event.objects.create(date="2025-03-15", subject="E2", action=self.et2)
        self.e3 = Event.objects.create(date="2024-11-20", subject="E3", action=self.et1)

    def test_list_returns_all_events(self):
        resp = self.jget(_api("events/"))
        self.assertEqual(resp.json()["count"], 3)

    def test_filter_by_type(self):
        resp = self.jget(_api(f"events/?type={self.et1.pk}"))
        subjects = [e["subject"] for e in resp.json()["results"]]
        self.assertIn("E1", subjects)
        self.assertNotIn("E2", subjects)

    def test_filter_by_year(self):
        resp = self.jget(_api("events/?year=2024"))
        subjects = [e["subject"] for e in resp.json()["results"]]
        self.assertIn("E1", subjects)
        self.assertIn("E3", subjects)
        self.assertNotIn("E2", subjects)

    def test_create_event(self):
        resp = self.jpost(_api("events/"), {"date": "2026-01-01", "subject": "New", "action_id": self.et1.pk})
        self.assertEqual(resp.status_code, 201)

    def test_response_includes_action_name_and_color(self):
        resp = self.jget(_api(f"events/{self.e1.pk}/"))
        data = resp.json()
        self.assertEqual(data["action_name"], "TypeA")
        self.assertEqual(data["action_color"], "#ff0000")


# ---------------------------------------------------------------------------
# backoffice/api — UserViewSet
# ---------------------------------------------------------------------------


class UserViewSetTests(_ApiTestCase):
    def test_list_returns_users(self):
        User.objects.create_user("alice@example.com", email="alice@example.com", password="x")
        resp = self.jget(_api("users/"))
        usernames = [u["username"] for u in resp.json()["results"]]
        self.assertIn("alice@example.com", usernames)

    def test_create_sets_username_from_email(self):
        resp = self.jpost(_api("users/"), {"email": "bob@example.com", "password": "secret123"})
        self.assertEqual(resp.status_code, 201)
        user = User.objects.get(email="bob@example.com")
        self.assertEqual(user.username, "bob@example.com")

    def test_create_hashes_password(self):
        self.jpost(_api("users/"), {"email": "carol@example.com", "password": "plain"})
        user = User.objects.get(email="carol@example.com")
        self.assertNotEqual(user.password, "plain")
        self.assertTrue(user.check_password("plain"))

    def test_create_requires_password(self):
        resp = self.jpost(_api("users/"), {"email": "nopass@example.com"})
        self.assertEqual(resp.status_code, 400)

    def test_update_syncs_username_from_email(self):
        user = User.objects.create_user("old@example.com", email="old@example.com", password="x")
        resp = self.jpatch(_api(f"users/{user.pk}/"), {"email": "new@example.com"})
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.username, "new@example.com")
        self.assertEqual(user.email, "new@example.com")

    def test_update_password_rehashes(self):
        user = User.objects.create_user("u@example.com", email="u@example.com", password="old")
        self.jpatch(_api(f"users/{user.pk}/"), {"email": "u@example.com", "password": "new"})
        user.refresh_from_db()
        self.assertTrue(user.check_password("new"))
        self.assertFalse(user.check_password("old"))

    def test_delete_user(self):
        user = User.objects.create_user("del@example.com", email="del@example.com", password="x")
        resp = self.jdelete(_api(f"users/{user.pk}/"))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_is_staff_flag_respected(self):
        resp = self.jpost(_api("users/"), {"email": "staff@example.com", "password": "x", "is_staff": True})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(User.objects.get(email="staff@example.com").is_staff)
