"""HTML 화면: 분석 화면, 작업 상세, 관리자 전용 대시보드.

대시보드 집계는 Django ORM으로 한다. FastAPI는 DB를 모르는 추론 전용 서비스이기 때문.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Avg, Count
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .action_catalog import UNCERTAIN, active_actions, active_set_name, display_name
from .job_state import expire_if_stale
from .models import AnalysisJob, PersonPrediction


@login_required
def index(request):
    recent = (
        AnalysisJob.objects.filter(user=request.user)
        .annotate(prediction_count=Count("predictions"))
        .prefetch_related("predictions")  # 이력 표에 대표 예측·신뢰도 표시 (N+1 방지)
        .order_by("-created_at")[:10]
    )
    cameras = [{"key": k, "label": v["label"]} for k, v in settings.IP_WEBCAMS.items()]
    return render(
        request,
        "analyses/index.html",
        {
            "recent_jobs": recent,
            "cameras": cameras,
            "actions": active_actions(),
            "action_set": active_set_name(),
            "capture_seconds": settings.CAPTURE_SECONDS,
            "max_upload_mb": settings.MAX_UPLOAD_MB,
        },
    )


@login_required
def job_detail(request, pk: int):
    job = get_object_or_404(AnalysisJob.objects.select_related("user"), pk=pk)
    if job.user_id != request.user.id and not request.user.is_staff:
        raise Http404  # 남의 작업은 존재 여부도 알리지 않음
    expire_if_stale(job)
    return render(request, "analyses/detail.html", {"job": job, "predictions": job.predictions.all()})


def _is_staff(user) -> bool:
    return user.is_authenticated and user.is_staff


@user_passes_test(_is_staff, login_url="accounts:login")
def dashboard(request):
    action_counts = dict(
        PersonPrediction.objects.values_list("action_label").annotate(n=Count("id")).values_list("action_label", "n")
    )
    status_counts = dict(
        AnalysisJob.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    input_counts = dict(
        AnalysisJob.objects.values_list("input_type").annotate(n=Count("id")).values_list("input_type", "n")
    )
    avg_times = {
        row["input_type"]: round(row["avg"] or 0, 2)
        for row in AnalysisJob.objects.filter(status=AnalysisJob.Status.SUCCESS)
        .values("input_type")
        .annotate(avg=Avg("total_time_sec"))
    }

    action_keys = [key for key, _ in active_actions()]
    action_keys += sorted(k for k in action_counts if k not in action_keys and k != UNCERTAIN)
    chart_data = {
        "actions": {
            # 현재 동작 목록 + (이전 모델로 저장된) 그 밖의 Label도 함께 표시
            "labels": [display_name(key) for key in action_keys],
            "values": [action_counts.get(key, 0) for key in action_keys],
        },
        "uncertain": action_counts.get(UNCERTAIN, 0),
        "statuses": {
            "labels": [label for _, label in AnalysisJob.Status.choices],
            "keys": [key for key, _ in AnalysisJob.Status.choices],
            "values": [status_counts.get(key, 0) for key, _ in AnalysisJob.Status.choices],
        },
        "inputs": {
            "labels": [label for _, label in AnalysisJob.InputType.choices],
            "values": [input_counts.get(key, 0) for key, _ in AnalysisJob.InputType.choices],
            "avg_time": [avg_times.get(key, 0) for key, _ in AnalysisJob.InputType.choices],
        },
    }
    recent = AnalysisJob.objects.select_related("user").order_by("-created_at")[:10]
    return render(
        request,
        "analyses/dashboard.html",
        {
            "chart_data": chart_data,
            "recent_jobs": recent,
            "total_jobs": sum(status_counts.values()),
            "total_predictions": sum(action_counts.values()),
        },
    )
