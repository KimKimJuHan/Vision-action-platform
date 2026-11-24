from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from . import page_views, views

app_name = "analyses"

router = DefaultRouter()
router.register("analyses", views.AnalysisJobViewSet, basename="analysis")

# API 주소는 두 규칙을 모두 지원한다.
#   /api/analyses/     과제 문서 (교과10_VisionAI_동작추론_자율프로젝트.md)
#   /api/v1/analyses/  9~10일차 단계별 개발 가이드의 권장 주소
urlpatterns = [
    path("", RedirectView.as_view(pattern_name="analyses:index", permanent=False)),
    path("analyses/", page_views.index, name="index"),
    path("analyses/<int:pk>/", page_views.job_detail, name="detail"),
    path("dashboard/", page_views.dashboard, name="dashboard"),
    path("api/cameras/", views.camera_list, name="camera-list"),
    path("api/v1/cameras/", views.camera_list),
    path("api/", include(router.urls)),
    path("api/v1/", include(router.urls)),
]
