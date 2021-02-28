from django.urls import path
from .views import IndexView, SigninView, SignupView, AuthView, ForgotView, ForgotVerifyView, ForgotResetView

app_name = "vclient"

urlpatterns = [
    path('api/signin/', SigninView.as_view(), name="signin"),
    path('api/signup/', SignupView.as_view(), name="signup"),
    path('api/forgot-password/', ForgotView.as_view(), name="forgot-password"),
    path('api/reset-confirm/', ForgotVerifyView.as_view(), name="reset-confirm"),
    path('api/reset-password/', ForgotResetView.as_view(), name="reset-password"),
    path('api/auth/', AuthView.as_view(), name="auth"),
    path('api/', IndexView.as_view(), name="index"),
]
