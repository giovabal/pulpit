from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_staff:
            return redirect(settings.LOGIN_URL)
        return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)


class ChannelsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/channels.html"


class OrganizationsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/organizations.html"


class GroupsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/groups.html"


class SearchTermsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/search_terms.html"


class EventsView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/events.html"
