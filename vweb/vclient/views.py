from django.template.loader import render_to_string
from django.http import HttpResponse
from django.views.generic import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.conf import settings
import logging
import urllib.request
import os
from vweb.vweb import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.core.mail import send_mail
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from vweb.utils import post_error, post_success
from . import models, serializers
import secrets
from django.core.mail import EmailMultiAlternatives
import hashlib

auth_logger = logging.getLogger(__name__)


class IndexView(View):
    def get(self, request):
        return HttpResponse(
            """
            This URL is only used when you have built the production
            version of the app. Visit http://localhost:3000/ instead, or
            run `yarn run build` to test the production version.
            """,
            status=501,
        )


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SigninView(APIView):
    permission_classes = [AllowAny]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def authenticate_user(self, username: str, userpass: str):
        user = authenticate(email=username, password=userpass)
        if user:
            # Generate new token
            token = models.Token(user=user, token=user.new_token)
            token.save()  # Save token to db
            return True, {'user': user, 'token': user.jwt_token(token.token)}
        else:
            return False, {"error": 201, "errorString": "Incorrect username or password"}

    def post(self, request, *args, **kwargs):
        serializer = serializers.LoginSerializer(data=request.data)
        state = serializer.is_valid(raise_exception=False)
        if state:
            username = serializer.validated_data.get('username')
            password = serializer.validated_data.get('password')
            success, response = self.authenticate_user(username, password)
            if success:
                user = response.get('user')
                jwt_token = response.get('token')
                data = {'userId': user.email, 'token': jwt_token, 'active': user.activated}
                return Response(post_success(data))
            else:
                auth_logger.warning("Incorrect Username or password : %s", username)
                return Response(post_error(response))
        else:
            errors = serializer.errors
            response_data = {}
            for field, errs in errors.items():
                field_errors = []
                for e in errs:
                    error = e.code
                    error_string = e
                    er = {
                        "error": error,
                        "errorString": str(error_string)
                    }
                    field_errors.append(er)
                response_data[field] = field_errors
            return Response({"errors": errors, 'data': request.data})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SignupView(APIView):
    permission_classes = [AllowAny]

    def __init__(self):
        super().__init__()

    def post(self, request, *args, **kwargs):
        """
        Receives the registration form and returns a response.
        """
        serializer = serializers.RegisterSerializer(data=request.data)
        state = serializer.is_valid(raise_exception=False)
        if state:
            # Attempt creating user With validated data
            # Database lock to avoid possible race condition
            user = None
            with transaction.atomic():
                try:
                    email = serializer.validated_data.get('username')
                    get_user_model().objects.get(email=email)
                except get_user_model().DoesNotExist:
                    pin = secrets.SystemRandom().randint(1000, 9999)
                    d = {
                        'password': serializer.validated_data.get('password'),
                        'email': serializer.validated_data.get('username')
                    }
                    user = get_user_model().objects.create_user(**d)
                    pin_obj = models.Pins(user=user, pin=pin)
                    pin_obj.save()
                else:
                    return Response(post_success({'status': False, 'data': {'error': 'User already exists.'}}))
            if user:
                # User created successfully
                subject, from_email, to = 'OTP Account Verification', 'verification@vbettrader.com', f'{email}'
                a = {'pin': pin, 'user': email}
                text_content = render_to_string('signup.txt', a)
                html_content = render_to_string('signup.html', a)
                msg = EmailMultiAlternatives(subject, text_content, from_email, [to])
                msg.attach_alternative(html_content, "text/html")
                msg.send()
                return Response(post_success({'status': True}))
            else:
                # Error in manager instance creating user
                return Response(post_success({'status': False, 'data': {'error': 'Something went wrong.'}}))
        else:
            # General Serialization errors occurred
            errors = serializer.errors
            response_data = {}
            for field, errs in errors.items():
                field_errors = []
                for e in errs:
                    error = e.code
                    error_string = e
                    er = {
                        "error": error,
                        "errorString": str(error_string)
                    }
                    field_errors.append(er)
                response_data[field] = field_errors
            return Response({"errors": errors, 'data': request.data})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class AuthView(APIView):
    permission_classes = [AllowAny]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def authenticate_user(self, username: str, pin: int):
        try:
            user = get_user_model().objects.get(email=username)
        except get_user_model().DoesNotExist:
            return Response(post_error({'message': 'Please enter a valid otp pin'}))
        else:
            try:
                p = models.Pins.objects.get(user=user)
            except models.Pins.DoesNotExist:
                return Response(post_error({'message': 'Please enter a valid otp pin'}))
            else:
                if pin == p.pin:
                    user.activated = True
                    user.save()
                    p.delete()
                    return Response(post_success({}))
            return Response(post_error({'message': 'Please enter a valid otp pin'}))

    def post(self, request, *args, **kwargs):
        serializer = serializers.AuthSerializer(data=request.data)
        state = serializer.is_valid(raise_exception=False)
        if state:
            username = serializer.validated_data.get('username')
            pin = serializer.validated_data.get('pin')
            return self.authenticate_user(username, pin)
        return Response(post_error({'message': 'Please enter a valid otp pin'}))


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ForgotView(APIView):
    permission_classes = [AllowAny]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def mail_user(self, email, token, user_id):
        subject, from_email, to = 'Reset Account Password', 'verification@vbettrader.com', f'{email}'
        a = {'link': f'https://vbettrader.com/forgot-password-verify/user={user_id}&guid={token}'}
        text_content = render_to_string('forgot.txt', a)
        html_content = render_to_string('forgot.html', a)
        msg = EmailMultiAlternatives(subject, text_content, from_email, [to])
        msg.attach_alternative(html_content, "text/html")
        msg.send()

    def authenticate_user(self, username: str):
        try:
            user = get_user_model().objects.get(email=username)
        except get_user_model().DoesNotExist:
            return Response(post_success({'message': ''}))
        else:
            token = secrets.token_urlsafe(32)
            fg = models.ForgotTokens(user=user, token=token)
            fg.save()
            a = fg.id
            self.mail_user(username, token, a)
            return Response(post_success({'message': ''}))

    def post(self, request, *args, **kwargs):
        serializer = serializers.ForgotSerializer(data=request.data)
        state = serializer.is_valid(raise_exception=False)
        if state:
            username = serializer.validated_data.get('username')
            return self.authenticate_user(username)
        return Response(post_error({'message': 'Please Enter a valid email'}))


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ForgotVerifyView(APIView):
    permission_classes = [AllowAny]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def authenticate_user(self, username: str, token: str):
        try:
            fg = models.ForgotTokens.objects.get(id=username, token=token)
            if fg.is_used:
                raise ValueError("")
        except (models.ForgotTokens.DoesNotExist, ValueError):
            return Response(post_error({'message': ''}))
        else:
            return Response(post_success({'message': ''}))

    def post(self, request, *args, **kwargs):
        serializer = serializers.ForgotResetSerializer(data=request.data)
        state = serializer.is_valid(raise_exception=False)
        if state:
            username = serializer.validated_data.get('username')
            token = serializer.validated_data.get('token')
            return self.authenticate_user(username, token)
        return Response(post_error({'message': ''}))


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ForgotResetView(APIView):
    permission_classes = [AllowAny]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def authenticate_user(self, username: str, token: str, password: str):
        try:
            fg = models.ForgotTokens.objects.get(id=username, token=token)
            if fg.is_used:
                raise ValueError("")
            fg.user.set_password(password)
            fg.is_used = True
            fg.user.save()
            fg.save()
        except (models.ForgotTokens.DoesNotExist, ValueError):
            return Response(post_error({'message': ''}))
        else:
            return Response(post_success({'message': ''}))

    def post(self, request, *args, **kwargs):
        serializer = serializers.ForgotResetConfirmSerializer(data=request.data)
        state = serializer.is_valid(raise_exception=False)
        if state:
            username = serializer.validated_data.get('username')
            token = serializer.validated_data.get('token')
            password = serializer.validated_data.get('password')
            return self.authenticate_user(username, token, password)
        return Response(post_error({'message': ''}))
