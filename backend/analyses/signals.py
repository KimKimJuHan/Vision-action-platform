"""삭제 정책: 작업을 지우면 사람별 예측은 CASCADE로 삭제되고, Media의 영상 파일도 함께 지운다.
(post_delete 시그널은 Admin 일괄 삭제·QuerySet.delete()에서도 호출된다)"""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import AnalysisJob


@receiver(post_delete, sender=AnalysisJob)
def delete_video_file(sender, instance: AnalysisJob, **kwargs):
    if instance.video_file:
        instance.video_file.delete(save=False)
