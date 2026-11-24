"""Django Admin: 전체 작업·사람별 결과 조회. AI가 만든 값은 읽기 전용."""
from django.contrib import admin
from django.db.models import Count

from .models import AnalysisJob, PersonPrediction


class PersonPredictionInline(admin.TabularInline):
    model = PersonPrediction
    extra = 0
    can_delete = False
    fields = ("track_id", "action_label", "confidence", "window_count", "vote_ratio", "is_uncertain")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "input_type", "status", "prediction_count",
        "expected_action", "total_time_sec", "created_at",
    )
    list_filter = ("status", "input_type", "expected_action", "created_at")
    search_fields = ("user__username", "title", "celery_task_id", "error_code")
    date_hierarchy = "created_at"
    list_select_related = ("user",)
    inlines = [PersonPredictionInline]
    readonly_fields = (
        "status", "celery_task_id", "error_code", "error_message", "result_message",
        "person_detected", "video_duration_sec", "inference_time_sec", "total_time_sec",
        "created_at", "started_at", "completed_at",
    )
    fieldsets = (
        ("요청", {"fields": ("user", "title", "memo", "input_type", "video_file", "camera_key",
                             "capture_seconds", "expected_action")}),
        ("처리 상태", {"fields": ("status", "celery_task_id", "error_code", "error_message", "result_message")}),
        ("결과 요약", {"fields": ("person_detected", "video_duration_sec", "inference_time_sec",
                                 "total_time_sec", "created_at", "started_at", "completed_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_prediction_count=Count("predictions"))

    @admin.display(description="예측 수", ordering="_prediction_count")
    def prediction_count(self, obj):
        return obj._prediction_count


@admin.register(PersonPrediction)
class PersonPredictionAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "job_user", "track_id", "action_label", "confidence",
                    "window_count", "is_uncertain", "created_at")
    list_filter = ("action_label", "is_uncertain", "job__input_type")
    search_fields = ("job__user__username", "job__id")
    list_select_related = ("job", "job__user")
    readonly_fields = [f.name for f in PersonPrediction._meta.fields]

    @admin.display(description="사용자", ordering="job__user__username")
    def job_user(self, obj):
        return obj.job.user.username

    def has_add_permission(self, request):
        return False
