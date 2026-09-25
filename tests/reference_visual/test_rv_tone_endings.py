"""Sentence-ending classifier shared by the reference analyzer (``aggregate.tone_items``), ``episode validate``
(``edit.validate.check_tone``) and output QA (``qa.probes_text.classify_register``).

음슴체 must be a PREDICATE nominalised with -(으)ㅁ (했음 / 들킴 / 발견됨 / 당황함 / 실화임).  Nouns that also end in
-ㅁ are register-neutral (명사형/기타): counting them as 음슴체 shifts the measured register -- the QA synthetic title
"실험 영상 모음" ('collection') was classified 음슴체 before this rule set.
"""
from __future__ import annotations

import pytest

from shortkit.reference import aggregate as A

EUMSEUM = [
    "결국 들킴", "아무도 모름", "그대로 사라짐", "깜짝 놀람", "게임 끝남", "몰래 도망감", "다 바뀜", "이건 아님",
    "정말 웃김", "다시 돌아옴", "문이 열림",
    "진짜 있었음", "답이 없음", "끝까지 했음", "혼자 갔음", "내일 오겠음", "이미 왔음",
    "기분 좋음", "완전 같음", "사람이 많음", "하나도 안 괜찮음", "혼자 다 먹음",
    "범인 발견됨", "결국 안됨", "됨", "완전 당황함", "그냥 함", "몰래 도착함",
    "이거 실화임", "역대급 레전드임", "뒤에서 보임",
    "너무 귀여움",
]
NOUN_M = [
    "실험 영상 모음", "레전드 영상 모음",          # 모음 'collection' (the QA synthetic title)
    "그 사람", "내 마음", "처음", "바로 다음", "새 이름", "요즘", "바로 지금", "아주 조금",
    "기억력 게임", "동네 모임", "작은 움직임", "고함", "배송비 포함", "치명적 결함", "모두 내 책임",
    "엄마의 웃음", "눈물의 싸움", "작은 도움", "어린 시절의 그림", "묘한 느낌", "그날의 기쁨", "소름",
    "사장님", "우리 선생님", "고객님",
    "엄청난 긴장감", "존재감", "고양이의 관심", "역대급 작품", "그의 진심", "최대 장점", "위험",
    "고양이의 귀여움",                               # genitive + nominal: a noun phrase
    "봄", "밤", "꿈", "감", "잠", "임", "먼저 옴",   # one-syllable -ㅁ words: too ambiguous (a missed
    #                                                   음슴체 only drops a sample)
    "싱싱한 얼음", "첫 걸음", "그리고 믿음",
]


@pytest.mark.parametrize("text", EUMSEUM)
def test_nominalised_predicates_are_eumseumche(text):
    r = A.ending_class(text)
    assert r is not None and r[0] == "음슴체", (text, r)


@pytest.mark.parametrize("text", NOUN_M)
def test_nouns_ending_in_mieum_are_register_neutral(text):
    r = A.ending_class(text)
    assert r is not None and r[0] == "명사형/기타", (text, r)


def test_other_classes_unchanged():
    assert A.ending_class("학생들이 모여 있다")[0] == "반말"
    assert A.ending_class("진짜 왔어요?")[0] == "해요체"
    assert A.ending_class("감사합니다")[0] == "합쇼체"
    assert A.ending_class("오늘의 사건")[0] == "명사형/기타"
    assert A.ending_class("결국 들킴!!")[0] == "음슴체"            # trailing punctuation stripped
    assert A.ending_class("") is None


def test_validate_and_qa_use_this_classifier():
    """One classifier: validate.check_tone and QA's classify_register import this very function."""
    from shortkit.edit import validate
    from shortkit.qa.probes_text import classify_register

    fn, reg_map = validate._ending_classifier()
    assert fn is A.ending_class and reg_map is A.REGISTER_MAP
    r = classify_register(["실험 영상 모음", "사람들이 모여 있다", "그냥 지나간다"])
    by_text = {it["text"]: it for it in r["items"]}
    assert by_text["실험 영상 모음"]["class"] == "명사형/기타" and by_text["실험 영상 모음"]["register"] is None
    assert r["mode"] == "반말_구어체"
