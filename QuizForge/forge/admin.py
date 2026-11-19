from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("QuizForge role", {"fields": ("teacher",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("QuizForge role", {"fields": ("teacher",)}),
    )
