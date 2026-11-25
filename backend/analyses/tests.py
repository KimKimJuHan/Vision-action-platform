"""과제 기능 테스트 (T05~T09 중 Django·Celery 부분).

실행: python manage.py test   (DB_ENGINE=sqlite 로 PostgreSQL 없이도 가능)
FastAPI 호출은 mock 으로 대체한다 (FastAPI 자체 테스트는 ai_service/tests).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import AnalysisJob, PersonPrediction
from .services import AIServiceError, AIServiceUnavailable, request_prediction
from .tasks import run_analysis

TMP_MEDIA = tempfile.mkdtemp(prefix="test_media_")
CAMERAS = {"phone1": {"label": "교실 휴대폰", "url": "http://192.168.0.10:8080/video"}}

FAKE_RESULT = {
    "status": "ok",
    "message": "2명의 동작을 예측했습니다.",
    "person_detected": True,
    "predictions": [
        {"track_id": 1, "action_label": "wave", "confidence": 0.92, "raw_label": "wave",
         "window_count": 9, "vote_ratio": 0.89, "is_uncertain": False, "first_seen_sec": 0.0, "last_seen_sec": 5.9,
         "valid_feature_ratio": 0.97},
        {"track_id": 2, "action_label": "sit_stand", "confidence": 0.81, "raw_label": "sit_stand",
         "window_count": 8, "vote_ratio": 0.75, "is_uncertain": False, "first_seen_sec": 0.2, "last_seen_sec": 5.9,
         "valid_feature_ratio": 0.41},
    ],
    "video": {"duration_sec": 6.0},
    "processing_time_sec": 3.21,
}


def video_upload(name="clip.mp4", content=b"\x00\x00\x00\x18ftypmp42" + b"0" * 1024):
    return SimpleUploadedFile(name, content, content_type="video/mp4")


@override_settings(MEDIA_ROOT=TMP_MEDIA, IP_WEBCAMS=CAMERAS, CAPTURE_SECONDS=8.0)
class AnalysisApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw-alice-123")
        self.bob = User.objects.create_user("bob", password="pw-bob-123")
        self.admin = User.objects.create_user("admin", password="pw-admin-123", is_staff=True)
        self.client_a = APIClient()
        self.client_a.force_authenticate(self.alice)
        self.client_b = APIClient()
        self.client_b.force_authenticate(self.bob)

    def _create_upload_job(self, client=None):
        client = client or self.client_a
        with mock.patch("analyses.views.run_analysis.apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                res = client.post(
                    "/api/analyses/",
                    {"input_type": "UPLOAD", "video_file": video_upload(), "expected_action": "wave"},
                    format="multipart",
                )
        return res, apply_async

    # ------------------------------------------------------------------ T05 비동기
    def test_t05_create_returns_202_and_job_id_without_waiting(self):
        res, apply_async = self._create_upload_job()
        self.assertEqual(res.status_code, 202, res.data)
        job = AnalysisJob.objects.get(pk=res.data["id"])
        self.assertEqual(job.status, "PENDING")
        self.assertEqual(job.celery_task_id, res.data["task_id"])
        # 커밋 이후에 같은 task_id 로 큐에 등록되었는가
        apply_async.assert_called_once_with(args=[job.pk], task_id=res.data["task_id"])

    def test_task_not_enqueued_before_commit(self):
        with mock.patch("analyses.views.run_analysis.apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.client_a.post("/api/analyses/", {"input_type": "UPLOAD", "video_file": video_upload()},
                                   format="multipart")
            apply_async.assert_not_called()  # 아직 커밋 전
            self.assertEqual(len(callbacks), 1)

    def test_upload_requires_file_and_valid_extension(self):
        res = self.client_a.post("/api/analyses/", {"input_type": "UPLOAD"}, format="multipart")
        self.assertEqual(res.status_code, 400)
        res = self.client_a.post(
            "/api/analyses/",
            {"input_type": "UPLOAD", "video_file": SimpleUploadedFile("a.txt", b"hello")},
            format="multipart",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("video_file", res.data)

    def test_ip_webcam_only_allowed_camera_key(self):
        res = self.client_a.post("/api/analyses/", {"input_type": "IP_WEBCAM", "camera_key": "http://evil/"})
        self.assertEqual(res.status_code, 400)
        with mock.patch("analyses.views.run_analysis.apply_async"):
            res = self.client_a.post("/api/analyses/", {"input_type": "IP_WEBCAM", "camera_key": "phone1"})
        self.assertEqual(res.status_code, 202)
        job = AnalysisJob.objects.get(pk=res.data["id"])
        self.assertEqual(job.capture_seconds, 8.0)
        self.assertFalse(job.video_file)

    def test_camera_list_hides_urls(self):
        res = self.client_a.get("/api/cameras/")
        self.assertEqual(res.data["cameras"], [{"key": "phone1", "label": "교실 휴대폰"}])
        self.assertNotIn("192.168", str(res.data))

    # ------------------------------------------------------------------ T07 권한
    def test_t07_user_cannot_read_update_delete_others_job(self):
        res, _ = self._create_upload_job(self.client_a)
        job_id = res.data["id"]
        self.assertEqual(self.client_b.get(f"/api/analyses/{job_id}/").status_code, 404)
        self.assertEqual(self.client_b.get(f"/api/analyses/{job_id}/status/").status_code, 404)
        self.assertEqual(self.client_b.patch(f"/api/analyses/{job_id}/", {"memo": "x"}).status_code, 404)
        self.assertEqual(self.client_b.delete(f"/api/analyses/{job_id}/").status_code, 404)
        self.assertEqual(self.client_b.get("/api/analyses/").data["count"], 0)
        self.assertEqual(self.client_a.get("/api/analyses/").data["count"], 1)

    def test_patch_allows_only_title_and_memo(self):
        res, _ = self._create_upload_job()
        job_id = res.data["id"]
        ok = self.client_a.patch(f"/api/analyses/{job_id}/", {"title": "새 제목", "memo": "메모"}, format="json")
        self.assertEqual(ok.status_code, 200)
        bad = self.client_a.patch(f"/api/analyses/{job_id}/", {"status": "SUCCESS"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(AnalysisJob.objects.get(pk=job_id).status, "PENDING")

    def test_put_not_allowed(self):
        res, _ = self._create_upload_job()
        self.assertEqual(self.client_a.put(f"/api/analyses/{res.data['id']}/", {}).status_code, 405)

    def test_delete_cascades_predictions_and_file(self):
        res, _ = self._create_upload_job()
        job = AnalysisJob.objects.get(pk=res.data["id"])
        job.status = AnalysisJob.Status.SUCCESS
        job.save()
        PersonPrediction.objects.create(job=job, track_id=1, action_label="wave", confidence=0.9, window_count=3)
        path = Path(job.video_file.path)
        self.assertTrue(path.exists())
        self.assertEqual(self.client_a.delete(f"/api/analyses/{job.pk}/").status_code, 204)
        self.assertEqual(PersonPrediction.objects.count(), 0)
        self.assertFalse(path.exists())

    def test_cannot_delete_running_job(self):
        res, _ = self._create_upload_job()
        AnalysisJob.objects.filter(pk=res.data["id"]).update(status="STARTED")
        self.assertEqual(self.client_a.delete(f"/api/analyses/{res.data['id']}/").status_code, 409)

    # ------------------------------------------------------------------ T06 결과 저장 (Celery 작업)
    def test_t06_task_saves_predictions_with_orm(self):
        res, _ = self._create_upload_job()
        job_id = res.data["id"]
        with mock.patch("analyses.tasks.request_prediction", return_value=FAKE_RESULT):
            run_analysis.apply(args=[job_id])
        job = AnalysisJob.objects.get(pk=job_id)
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.predictions.count(), 2)
        self.assertEqual(job.predictions.get(track_id=1).action_label, "wave")
        self.assertIsNotNone(job.completed_at)
        detail = self.client_a.get(f"/api/analyses/{job_id}/").data
        self.assertEqual([p["track_id"] for p in detail["predictions"]], [1, 2])

    def test_task_is_idempotent_when_rerun(self):
        res, _ = self._create_upload_job()
        job_id = res.data["id"]
        with mock.patch("analyses.tasks.request_prediction", return_value=FAKE_RESULT) as req:
            run_analysis.apply(args=[job_id])
            run_analysis.apply(args=[job_id])  # 이미 완료 → 건너뜀
        self.assertEqual(req.call_count, 1)
        self.assertEqual(PersonPrediction.objects.filter(job_id=job_id).count(), 2)

    # ------------------------------------------------------------------ T09 예외 처리
    def test_t09_corrupt_video_marks_failure(self):
        res, _ = self._create_upload_job()
        job_id = res.data["id"]
        error = AIServiceError("VIDEO_UNREADABLE", "영상을 열 수 없습니다.", 422)
        with mock.patch("analyses.tasks.request_prediction", side_effect=error):
            run_analysis.apply(args=[job_id])
        job = AnalysisJob.objects.get(pk=job_id)
        self.assertEqual(job.status, "FAILURE")
        self.assertEqual(job.error_code, "VIDEO_UNREADABLE")
        status = self.client_a.get(f"/api/analyses/{job_id}/status/").data
        self.assertTrue(status["done"])

    def test_t09_camera_disconnect_marks_failure(self):
        from .camera_capture import CaptureError

        with mock.patch("analyses.views.run_analysis.apply_async"):
            res = self.client_a.post("/api/analyses/", {"input_type": "IP_WEBCAM", "camera_key": "phone1"})
        err = CaptureError("CAMERA_UNAVAILABLE", "카메라에 연결할 수 없습니다.")
        with mock.patch("analyses.tasks.capture_clip", side_effect=err):
            run_analysis.apply(args=[res.data["id"]])
        job = AnalysisJob.objects.get(pk=res.data["id"])
        self.assertEqual((job.status, job.error_code), ("FAILURE", "CAMERA_UNAVAILABLE"))

    def test_ai_unavailable_retries_then_fails(self):
        res, _ = self._create_upload_job()
        job_id = res.data["id"]
        with mock.patch("analyses.tasks.request_prediction", side_effect=AIServiceUnavailable("down")) as req:
            with mock.patch("analyses.tasks.RETRY_DELAY_SEC", 0):
                run_analysis.apply(args=[job_id])
        self.assertEqual(req.call_count, 4)  # 최초 1회 + 재시도 3회
        self.assertEqual(AnalysisJob.objects.get(pk=job_id).error_code, "AI_UNAVAILABLE")

    def test_no_person_is_success_with_empty_predictions(self):
        res, _ = self._create_upload_job()
        empty = {**FAKE_RESULT, "predictions": [], "person_detected": False, "message": "영상에서 사람을 찾지 못했습니다."}
        with mock.patch("analyses.tasks.request_prediction", return_value=empty):
            run_analysis.apply(args=[res.data["id"]])
        job = AnalysisJob.objects.get(pk=res.data["id"])
        self.assertEqual((job.status, job.person_detected), ("SUCCESS", False))
        self.assertEqual(job.predictions.count(), 0)

    # ------------------------------------------------------------------ T08 관리자
    def test_t08_dashboard_staff_only(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/dashboard/").status_code, 302)
        self.client.force_login(self.admin)
        res = self.client.get("/dashboard/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("chart_data", res.context)
        self.assertEqual(len(res.context["chart_data"]["actions"]["values"]), 6)

    def test_staff_sees_all_jobs_in_api(self):
        self._create_upload_job(self.client_a)
        self._create_upload_job(self.client_b)
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        self.assertEqual(admin_client.get("/api/analyses/").data["count"], 2)

    def test_pages_render(self):
        self.client.force_login(self.alice)
        self.assertRedirects(self.client.get("/"), "/analyses/")
        self.assertEqual(self.client.get("/analyses/").status_code, 200)
        res, _ = self._create_upload_job()
        self.assertEqual(self.client.get(f"/analyses/{res.data['id']}/").status_code, 200)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(f"/analyses/{res.data['id']}/").status_code, 404)

    def test_history_shows_comparison_columns(self):
        """최근 이력: 입력 방식·수행한 동작·대표 예측(신뢰도)·처리 시간을 한 줄에 표시 (두 입력 비교)."""
        job = AnalysisJob.objects.create(
            user=self.alice, input_type=AnalysisJob.InputType.IP_WEBCAM, camera_key="phone1",
            expected_action="wave", status=AnalysisJob.Status.SUCCESS, total_time_sec=18.8,
        )
        PersonPrediction.objects.create(job=job, track_id=1, action_label="wave", confidence=0.84, window_count=21)
        PersonPrediction.objects.create(job=job, track_id=2, action_label="sit_stand", confidence=0.6, window_count=5)
        self.client.force_login(self.alice)
        html = self.client.get("/analyses/").content.decode()
        self.assertIn("84%", html)
        self.assertIn("외 1명", html)
        self.assertIn("18.8초", html)

    def test_guide_v1_api_alias(self):
        """9~10일차 개발 가이드 권장 주소(/api/v1/analyses/)도 같은 API로 동작."""
        with mock.patch("analyses.views.run_analysis.apply_async"):
            res = self.client_a.post(
                "/api/v1/analyses/", {"input_type": "UPLOAD", "video_file": video_upload()}, format="multipart"
            )
        self.assertEqual(res.status_code, 202)
        job_id = res.data["id"]
        self.assertEqual(self.client_a.get(f"/api/v1/analyses/{job_id}/").status_code, 200)
        self.assertEqual(self.client_b.get(f"/api/v1/analyses/{job_id}/").status_code, 404)


@override_settings(MEDIA_ROOT=TMP_MEDIA, IP_WEBCAMS=CAMERAS, CAPTURE_SECONDS=8.0, JOB_STALE_SECONDS=720)
class JobReliabilityTests(TestCase):
    """멈춘 작업 정리, 재시도 범위, 카메라 재촬영 방지."""

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw-alice-123")
        self.client_a = APIClient()
        self.client_a.force_authenticate(self.alice)

    def _job(self, **fields):
        defaults = {"user": self.alice, "input_type": AnalysisJob.InputType.UPLOAD}
        return AnalysisJob.objects.create(**{**defaults, **fields})

    def test_retry_reuses_captured_webcam_clip(self):
        job = self._job(input_type=AnalysisJob.InputType.IP_WEBCAM, camera_key="phone1")

        def fake_capture(url, seconds, output_path, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"captured")
            return {"frames": 100, "fps": 12.5, "duration_sec": 8.0}

        calls = [AIServiceUnavailable("모델 로딩 중"), FAKE_RESULT]
        with mock.patch("analyses.tasks.capture_clip", side_effect=fake_capture) as capture, \
                mock.patch("analyses.tasks.request_prediction", side_effect=calls), \
                mock.patch("analyses.tasks.RETRY_DELAY_SEC", 0):
            run_analysis.apply(args=[job.pk])
        job.refresh_from_db()
        self.assertEqual(job.status, AnalysisJob.Status.SUCCESS)
        self.assertEqual(capture.call_count, 1)  # 재시도에서는 다시 촬영하지 않는다

    def test_stale_started_job_becomes_failure_and_deletable(self):
        job = self._job(status=AnalysisJob.Status.STARTED, started_at=timezone.now() - timedelta(seconds=721))
        res = self.client_a.get(f"/api/analyses/{job.pk}/status/")
        self.assertEqual(res.data["status"], "FAILURE")
        self.assertTrue(res.data["done"])
        self.assertEqual(res.data["error_code"], "WORKER_TIMEOUT")
        self.assertEqual(self.client_a.delete(f"/api/analyses/{job.pk}/").status_code, 204)

    def test_recent_started_job_is_left_alone(self):
        job = self._job(status=AnalysisJob.Status.STARTED, started_at=timezone.now() - timedelta(seconds=30))
        res = self.client_a.get(f"/api/analyses/{job.pk}/status/")
        self.assertEqual(res.data["status"], "STARTED")
        self.assertEqual(self.client_a.delete(f"/api/analyses/{job.pk}/").status_code, 409)

    def test_worker_does_not_overwrite_expired_job(self):
        job = self._job(video_file="uploads/x.mp4")

        def expire_then_answer(path):
            AnalysisJob.objects.filter(pk=job.pk).update(status=AnalysisJob.Status.FAILURE, error_code="WORKER_TIMEOUT")
            return FAKE_RESULT

        with mock.patch("analyses.tasks._acquire_video", return_value=Path("x.mp4")), \
                mock.patch("analyses.tasks.request_prediction", side_effect=expire_then_answer):
            run_analysis.apply(args=[job.pk])
        job.refresh_from_db()
        self.assertEqual(job.status, AnalysisJob.Status.FAILURE)
        self.assertEqual(job.predictions.count(), 0)

    def test_input_quality_is_saved_and_returned(self):
        job = self._job(video_file="uploads/x.mp4")
        with mock.patch("analyses.tasks._acquire_video", return_value=Path("x.mp4")), \
                mock.patch("analyses.tasks.request_prediction", return_value=FAKE_RESULT):
            run_analysis.apply(args=[job.pk])
        body = self.client_a.get(f"/api/analyses/{job.pk}/").data
        by_track = {p["track_id"]: p for p in body["predictions"]}
        self.assertEqual(by_track[1]["valid_feature_ratio"], 0.97)
        self.assertFalse(by_track[1]["is_low_quality"])
        self.assertTrue(by_track[2]["is_low_quality"])  # 0.41 < 0.6
        self.client_a.force_login(self.alice)
        html = self.client_a.get(f"/analyses/{job.pk}/").content.decode()
        self.assertIn("입력 품질", html)
        self.assertIn("낮음", html)

    def test_only_503_and_connection_errors_are_retryable(self):
        video = Path(TMP_MEDIA) / "svc.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"0")

        def response(status, code):
            fake = mock.Mock(status_code=status)
            fake.json.return_value = {"detail": {"code": code, "message": "m"}}
            return fake

        with mock.patch("analyses.services.requests.post", return_value=response(503, "MODEL_NOT_READY")):
            with self.assertRaises(AIServiceUnavailable):
                request_prediction(video)
        with mock.patch("analyses.services.requests.post", return_value=response(500, "INFERENCE_ERROR")):
            with self.assertRaises(AIServiceError) as ctx:
                request_prediction(video)
        self.assertEqual(ctx.exception.code, "INFERENCE_ERROR")


class ActionCatalogTests(TestCase):
    """동작 목록은 ACTION_SET으로 바뀐다 (basic 6개 · team 3개 · team6 6개)."""

    def setUp(self):
        self.user = User.objects.create_user("carol", password="pw-carol-123")
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_team_set_accepts_team_actions_only(self):
        with mock.patch.dict("os.environ", {"ACTION_SET": "team"}), \
                mock.patch("analyses.views.run_analysis.apply_async"):
            ok = self.api.post("/api/analyses/", {"input_type": "UPLOAD", "video_file": video_upload(),
                                                  "expected_action": "side_lying_leg_raise"}, format="multipart")
            bad = self.api.post("/api/analyses/", {"input_type": "UPLOAD", "video_file": video_upload(),
                                                   "expected_action": "wave"}, format="multipart")
        self.assertEqual(ok.status_code, 202, ok.data)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(AnalysisJob.objects.get(pk=ok.data["id"]).expected_action_display, "A006 옆으로 누워 다리 들기")

    def test_team_prediction_display_and_dashboard(self):
        job = AnalysisJob.objects.create(user=self.user, input_type="UPLOAD", status="SUCCESS")
        PersonPrediction.objects.create(job=job, track_id=1, action_label="side_lying_leg_raise",
                                        confidence=0.9, window_count=5)
        PersonPrediction.objects.create(job=job, track_id=2, action_label="wave", confidence=0.8, window_count=3)
        detail = self.api.get(f"/api/analyses/{job.pk}/").data
        self.assertEqual(detail["predictions"][0]["action_display"], "A006 옆으로 누워 다리 들기")
        admin = User.objects.create_user("boss", password="pw-boss-123", is_staff=True)
        self.client.force_login(admin)
        with mock.patch.dict("os.environ", {"ACTION_SET": "team"}):
            res = self.client.get("/dashboard/")
        labels = res.context["chart_data"]["actions"]["labels"]
        self.assertEqual(labels[:3], ["A001 앉아서 다리 앞으로 뻗기", "A002 팔 위아래로 뻗기", "A006 옆으로 누워 다리 들기"])
        self.assertIn("A006 손 흔들기", labels)  # 이전 모델로 저장된 기록도 차트에 남음
        with mock.patch.dict("os.environ", {"ACTION_SET": "team"}):
            page = self.client.get("/analyses/")
        self.assertContains(page, "A006 옆으로 누워 다리 들기")
        self.assertNotContains(page, "A010 버드독")  # team = 3동작

    def test_team6_set_has_six_actions(self):
        with mock.patch.dict("os.environ", {"ACTION_SET": "team6"}):
            from .action_catalog import active_actions
            self.assertEqual(len(active_actions()), 6)
            self.assertIn("bird_dog", [k for k, _ in active_actions()])
