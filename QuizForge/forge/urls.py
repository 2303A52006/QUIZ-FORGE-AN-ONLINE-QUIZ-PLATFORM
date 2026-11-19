from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from . import views as v

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", v.home, name="home"),
    path(
        "login/",
        LoginView.as_view(
            template_name="form.html",
            redirect_authenticated_user=True,
            extra_context={"title": "Welcome back"},
        ),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
] + [
    path(route, view, name=name)
    for route, view, name in [
        ("register/", v.register, "register"),
        ("studio/", v.studio, "studio"),
        ("profile/", v.profile, "profile"),
        ("build/", v.build, "build"),
        ("quiz/<int:pk>/edit/", v.build, "edit"),
        ("quiz/<int:pk>/copy/", v.duplicate, "duplicate"),
        ("quiz/<int:pk>/start/", v.start, "start"),
        ("attempt/<int:pk>/", v.take, "take"),
        ("result/<int:pk>/", v.result, "result"),
        ("quiz/<int:pk>/board/", v.board, "board"),
        ("quiz/<int:pk>/analytics/", v.analytics, "analytics"),
        ("quiz/<int:pk>/csv/", v.export, "csv"),
    ]
]
