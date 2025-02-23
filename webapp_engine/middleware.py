from django.contrib.auth.models import User


class AuthenticationMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user = User()
        return self.get_response(request)
