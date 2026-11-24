from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Vision Action 관리자"
admin.site.site_title = "Vision Action Admin"

urlpatterns = [
    path("admin/", admin.site.urls),  # Django Admin (DRF가 아님)
    path("accounts/", include("accounts.urls")),
    path("", include("analyses.urls")),  # 분석 화면 · /dashboard/ · /api/...
]
