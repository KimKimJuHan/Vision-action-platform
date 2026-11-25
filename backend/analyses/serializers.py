"""입력 검증과 JSON 표현.

- 생성(Create): 입력 방식에 맞는 필드만 받는다 (업로드 파일 / 허용된 camera_key).
- 수정(Update): title, memo 만 허용. status·예측 결과는 AI 처리 결과이므로 사용자가 바꿀 수 없다.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from .action_catalog import active_actions
from .models import AnalysisJob, PersonPrediction


class PersonPredictionSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(read_only=True)
    is_low_quality = serializers.BooleanField(read_only=True)

    class Meta:
        model = PersonPrediction
        fields = [
            "track_id", "action_label", "action_display", "raw_label", "confidence",
            "window_count", "vote_ratio", "is_uncertain", "valid_feature_ratio", "is_low_quality",
            "first_seen_sec", "last_seen_sec",
        ]
        read_only_fields = fields


class AnalysisJobSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    input_type_display = serializers.CharField(source="get_input_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    predictions = PersonPredictionSerializer(many=True, read_only=True)
    expected_action_display = serializers.CharField(read_only=True)
    video_name = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisJob
        fields = [
            "id", "username", "title", "memo",
            "input_type", "input_type_display", "video_file", "video_name",
            "camera_key", "capture_seconds", "expected_action", "expected_action_display",
            "status", "status_display", "celery_task_id", "error_code", "error_message",
            "result_message", "person_detected", "video_duration_sec",
            "inference_time_sec", "total_time_sec",
            "created_at", "started_at", "completed_at", "predictions",
        ]
        read_only_fields = [
            "id", "username", "status", "celery_task_id", "error_code", "error_message",
            "result_message", "person_detected", "video_duration_sec", "inference_time_sec",
            "total_time_sec", "capture_seconds", "created_at", "started_at", "completed_at",
        ]
        extra_kwargs = {"video_file": {"write_only": True, "required": False}}

    def get_video_name(self, obj) -> str:
        return Path(obj.video_file.name).name if obj.video_file else ""

    def validate_video_file(self, file):
        if file is None:
            return file
        suffix = Path(file.name).suffix.lower()
        if suffix not in settings.ALLOWED_VIDEO_EXTENSIONS:
            raise serializers.ValidationError(
                f"mp4·mov·avi·mkv 영상만 업로드할 수 있습니다. (받은 형식: {suffix or '없음'})"
            )
        if file.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise serializers.ValidationError(f"영상은 {settings.MAX_UPLOAD_MB}MB 이하만 허용합니다.")
        if file.size == 0:
            raise serializers.ValidationError("빈 파일입니다.")
        return file

    def validate_expected_action(self, value):
        allowed = {key for key, _ in active_actions()}
        if value and value not in allowed:
            raise serializers.ValidationError(f"선택할 수 없는 동작입니다: {value}")
        return value

    def validate(self, attrs):
        input_type = attrs.get("input_type")
        if input_type == AnalysisJob.InputType.UPLOAD:
            if not attrs.get("video_file"):
                raise serializers.ValidationError({"video_file": "분석할 영상을 선택하세요."})
            attrs["camera_key"] = ""
        elif input_type == AnalysisJob.InputType.IP_WEBCAM:
            key = attrs.get("camera_key", "")
            if key not in settings.IP_WEBCAMS:
                raise serializers.ValidationError({"camera_key": "허용된 카메라만 선택할 수 있습니다."})
            attrs.pop("video_file", None)
            attrs["capture_seconds"] = settings.CAPTURE_SECONDS
        return attrs


class AnalysisJobUpdateSerializer(serializers.ModelSerializer):
    """PATCH 전용: 제목·메모만 수정."""

    class Meta:
        model = AnalysisJob
        fields = ["title", "memo"]


class AnalysisJobStatusSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    done = serializers.BooleanField(source="is_done", read_only=True)
    prediction_count = serializers.IntegerField(source="predictions.count", read_only=True)

    class Meta:
        model = AnalysisJob
        fields = [
            "id", "status", "status_display", "done", "error_code", "error_message",
            "result_message", "prediction_count", "started_at", "completed_at",
        ]
        read_only_fields = fields
