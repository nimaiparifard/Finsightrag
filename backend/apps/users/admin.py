from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class FinSightUserAdmin(UserAdmin):
    ordering = ["email"]
    list_display = ["email", "role", "is_staff"]
    search_fields = ["email"]
    fieldsets = [(None, {"fields": ("email", "password")}), ("Access", {"fields": ("role", "is_active", "is_staff", "is_superuser")})]
    add_fieldsets = [(None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role")})]
