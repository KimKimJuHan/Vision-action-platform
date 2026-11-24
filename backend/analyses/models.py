"""ERD: auth_user 1:N AnalysisJob 1:N PersonPrediction

- 영상 파일 자체는 DB에 넣지 않는다. Media 볼륨에 저장하고 DB에는 경로(FileField)만 기록.
- 원본 Keypoint 시퀀스는 저장하지 않는다. FastAPI 메모리에서 추론하고 'Track별 결과'만 남긴다.
- track_id 는 '그 작업(영상) 안의' 추적 번호이며 사람의 영구 ID가 아니다.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from .action_catalog import display_name


class AnalysisJob(models.Model):
    class InputType(models.TextChoices):
        UPLOAD = "UPLOAD", "영상 업로드"
        IP_WEBCAM = "IP_WEBCAM", "IP Webcam"

    class Status(models.TextChoices):
        # Celery 상태 이름과 동일하게 통일
        PENDING = "PENDING", "대기"
        STARTED = "STARTED", "처리 중"
        SUCCESS = "SUCCESS", "완료"
        FAILURE = "FAILURE", "실패"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analysis_jobs"
    )
    title = models.CharField("제목", max_length=100, blank=True)
    memo = models.TextField("메모", blank=True)

    input_type = models.CharField("입력 방식", max_length=16, choices=InputType.choices)
    video_file = models.FileField("영상 경로", upload_to="uploads/%Y/%m/%d/", blank=True)
    camera_key = models.CharField("카메라", max_length=50, blank=True)  # URL이 아니라 허용 목록의 key
    capture_seconds = models.FloatField("수집 시간(초)", null=True, blank=True)
    # 사용자가 '수행하려는' 동작. 검증된 정답 Label이 아니다.
    # choices를 고정하지 않는다: 허용 값은 action_catalog(ACTION_SET)로 serializer에서 검사
    expected_action = models.CharField("수행한 동작(사용자 입력)", max_length=40, blank=True)

    status = models.CharField(
        "상태", max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    celery_task_id = models.CharField("Celery task ID", max_length=64, blank=True, db_index=True)
    error_code = models.CharField("오류 코드", max_length=50, blank=True)
    error_message = models.TextField("오류 메시지", blank=True)
    result_message = models.CharField("결과 메시지", max_length=255, blank=True)

    video_duration_sec = models.FloatField("영상 길이(초)", null=True, blank=True)
    inference_time_sec = models.FloatField("AI 추론 시간(초)", null=True, blank=True)
    total_time_sec = models.FloatField("전체 처리 시간(초)", null=True, blank=True)
    person_detected = models.BooleanField("사람 검출", null=True, blank=True)

    created_at = models.DateTimeField("생성", auto_now_add=True, db_index=True)
    started_at = models.DateTimeField("시작", null=True, blank=True)
    completed_at = models.DateTimeField("완료", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "분석 작업"
        verbose_name_plural = "분석 작업"
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"#{self.pk} {self.get_input_type_display()} {self.status}"

    @property
    def expected_action_display(self) -> str:
        return display_name(self.expected_action) if self.expected_action else ""

    @property
    def is_done(self) -> bool:
        return self.status in (self.Status.SUCCESS, self.Status.FAILURE)


class PersonPrediction(models.Model):
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name="predictions")
    track_id = models.PositiveIntegerField("Track ID")
    action_label = models.CharField("예측 동작", max_length=40)  # 모델 classes_ 값 또는 UNCERTAIN
    raw_label = models.CharField("최다 원시 예측", max_length=32, blank=True)
    confidence = models.FloatField("Confidence")
    window_count = models.PositiveIntegerField("처리 Window 수")
    vote_ratio = models.FloatField("득표율", default=0.0)
    is_uncertain = models.BooleanField("판단 불확실", default=False)
    first_seen_sec = models.FloatField("첫 등장(초)", null=True, blank=True)
    last_seen_sec = models.FloatField("마지막 등장(초)", null=True, blank=True)
    created_at = models.DateTimeField("예측 시간", auto_now_add=True)

    class Meta:
        ordering = ["job", "track_id"]
        verbose_name = "사람별 예측"
        verbose_name_plural = "사람별 예측"
        constraints = [
            models.UniqueConstraint(fields=["job", "track_id"], name="uniq_prediction_per_track")
        ]

    @property
    def action_display(self) -> str:
        return display_name(self.action_label)

    def __str__(self) -> str:
        return f"job#{self.job_id} track {self.track_id}: {self.action_label} ({self.confidence:.2f})"
