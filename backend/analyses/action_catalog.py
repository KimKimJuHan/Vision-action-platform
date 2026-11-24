"""서비스가 다루는 동작 목록. `.env`의 ACTION_SET으로 선택한다.

- basic: 과제 기본 6개 동작 (6일차 모델 / v2 모델) — 평가 기준 동작
- team : 팀 재활 운동 3개 동작 (팀원이 학습한 3동작 모델, 팀 영상 A001·A002·A006)
- team6: 팀 재활 운동 6개 동작 (11/17 추가 촬영까지 넣어 다시 학습한 확장 실험 모델)

DB에는 영문 Label(모델의 classes_)을 그대로 저장하고, 화면 표시 이름만 여기서 바꾼다.
그래서 동작 목록을 바꿔도 마이그레이션이 필요 없고, 이전 기록도 그대로 조회된다.
"""
from __future__ import annotations

import os

UNCERTAIN = "UNCERTAIN"

ACTION_SETS: dict[str, list[tuple[str, str]]] = {
    "basic": [
        ("bend_return", "A001 허리 굽혔다 펴기"),
        ("leg_raise_lower", "A002 한쪽 다리 들었다 내리기"),
        ("walk_turn_walk", "A003 걷다가 방향 바꾸기"),
        ("drink_return", "A004 음료 마시기"),
        ("sit_stand", "A005 앉았다 일어나기"),
        ("wave", "A006 손 흔들기"),
    ],
    # 팀 기획서 action_map.csv 의 번호·이름 기준. 팀 공식 모델 = 3동작
    "team": [
        ("seated_knee_extension", "A001 앉아서 다리 앞으로 뻗기"),
        ("shoulder_reach_up_down", "A002 팔 위아래로 뻗기"),
        ("side_lying_leg_raise", "A006 옆으로 누워 다리 들기"),
    ],
    # 확장 실험: 11/17 추가 촬영(A003·A009·A010)까지 넣은 6동작
    "team6": [
        ("seated_knee_extension", "A001 앉아서 다리 앞으로 뻗기"),
        ("shoulder_reach_up_down", "A002 팔 위아래로 뻗기"),
        ("foam_roller_hip_hinge", "A003 폼롤러 힙힌지"),
        ("side_lying_leg_raise", "A006 옆으로 누워 다리 들기"),
        ("adductor_bridge", "A009 무릎 모으며 엉덩이 들기"),
        ("bird_dog", "A010 버드독"),
    ],
}

# 이전에 저장된 기록이 다른 동작 목록이어도 이름이 보이도록 전체 이름표를 둔다
ALL_DISPLAY_NAMES: dict[str, str] = {
    key: name for actions in ACTION_SETS.values() for key, name in actions
}
ALL_DISPLAY_NAMES[UNCERTAIN] = "판단 불확실"


def active_set_name() -> str:
    name = os.getenv("ACTION_SET", "basic").strip().lower()
    return name if name in ACTION_SETS else "basic"


def active_actions() -> list[tuple[str, str]]:
    """현재 서비스에서 고를 수 있는 동작 (화면 선택지·대시보드 기본 막대)."""
    return ACTION_SETS[active_set_name()]


def display_name(label: str) -> str:
    return ALL_DISPLAY_NAMES.get(label, label)
