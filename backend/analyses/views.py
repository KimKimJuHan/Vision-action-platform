"""DRF API: 분석 작업 CRUD + 상태 조회.

POST   /api/analyses/              작업 생성 → DB 커밋 후 Celery 등록 → 202 + 작업 ID 즉시 반환
GET    /api/analyses/              내 작업 목록 (관리자는 전체)
GET    /api/analyses/{id}/         상세 + 사람별 예측
PATCH  /api/analyses/{id}/         제목·메모만 수정
DELETE /api/analyses/{id}/         작업·예측·영상 파일 삭제 (처리 중에는 거부)
GET    /api/analyses/{id}/status/  상태 Polling 용 가벼운 응답
GET    /api/cameras/               선택 가능한 카메라 목록 (URL은 노출하지 않음)
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .job_state import expire_if_stale
from .models import AnalysisJob
from .serializers import (
    AnalysisJobSerializer,
    AnalysisJobStatusSerializer,
    AnalysisJobUpdateSerializer,
)
from .tasks import run_analysis


class AnalysisJobViewSet(viewsets.ModelViewSet):
    serializer_class = AnalysisJobSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]  # PUT 미지원

    def get_queryset(self):
        # 조회 범위 제한: 다른 사람의 작업은 존재 자체가 보이지 않도록 404
        qs = AnalysisJob.objects.select_related("user").prefetch_related("predictions")
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)

    def get_object(self):
        # 상세·상태·삭제 모두 이 메서드를 거친다 → 멈춘 작업은 여기서 실패로 정리
        job = super().get_object()
        expire_if_stale(job)
        return job

    def get_serializer_class(self):
        if self.action == "partial_update":
            return AnalysisJobUpdateSerializer
        if self.action == "status":
            return AnalysisJobStatusSerializer
        return AnalysisJobSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task_id = str(uuid.uuid4())  # task ID를 먼저 정해 DB에 함께 저장
        with transaction.atomic():
            job = serializer.save(user=request.user, celery_task_id=task_id)
            # 트랜잭션이 커밋된 '뒤'에 큐에 넣는다.
            # 커밋 전에 넣으면 Worker가 아직 없는 Job을 조회하는 경쟁 상태가 생긴다.
            transaction.on_commit(lambda: run_analysis.apply_async(args=[job.pk], task_id=task_id))

        return Response(
            {
                "id": job.pk,
                "task_id": task_id,
                "status": job.status,
                "status_url": f"/api/analyses/{job.pk}/status/",
                "detail_url": f"/api/analyses/{job.pk}/",
            },
            status=status.HTTP_202_ACCEPTED,  # 접수만 하고 결과는 나중에
        )

    def partial_update(self, request, *args, **kwargs):
        job = self.get_object()
        if job.user_id != request.user.id:  # 관리자도 남의 메모는 API로 수정하지 않음 (Admin 사용)
            return Response({"detail": "본인 작업만 수정할 수 있습니다."}, status=status.HTTP_403_FORBIDDEN)
        serializer = AnalysisJobUpdateSerializer(job, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        unknown = set(request.data.keys()) - {"title", "memo"}
        if unknown:
            return Response(
                {"detail": f"수정할 수 없는 항목입니다: {sorted(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # update_fields로 저장 → 동시에 Worker가 바꾸는 status 등을 덮어쓰지 않음
        for field, value in serializer.validated_data.items():
            setattr(job, field, value)
        job.save(update_fields=list(serializer.validated_data.keys()))
        return Response(AnalysisJobSerializer(job, context={"request": request}).data)

    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        if job.user_id != request.user.id and not request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if job.status == AnalysisJob.Status.STARTED:
            return Response(
                {"detail": "처리 중인 작업은 완료 후 삭제할 수 있습니다."},
                status=status.HTTP_409_CONFLICT,
            )
        job.delete()  # predictions CASCADE + signals.py에서 영상 파일 삭제
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        job = self.get_object()
        return Response(AnalysisJobStatusSerializer(job).data)


@api_view(["GET"])
def camera_list(request):
    cameras = [{"key": key, "label": cam["label"]} for key, cam in settings.IP_WEBCAMS.items()]
    return Response({"cameras": cameras, "capture_seconds": settings.CAPTURE_SECONDS})
