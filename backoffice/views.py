from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView


def _web_access_is_all():
    return getattr(settings, "WEB_ACCESS", "ALL").upper() == "ALL"


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if _web_access_is_all():
            return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_staff:
            return redirect(settings.LOGIN_URL)
        return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)


class ChannelsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/channels.html"


class ChannelUpdateView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/channel_update.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["channel_pk"] = self.kwargs["pk"]
        return ctx


class OrganizationsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/organizations.html"


class GroupsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/groups.html"


class SearchTermsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/search_terms.html"


class EventsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/events.html"


class UsersView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/users.html"


class MessagesView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/messages.html"
