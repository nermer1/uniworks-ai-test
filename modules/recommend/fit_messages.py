"""
FIT_REASON 문구 사전
--------------------
계정 적합성 근거 문장(FIT_REASON)에 쓰이는 모든 문구의 **기본값 + UI 메타데이터**.

문장을 만드는 로직은 `core.evaluate_fitness`에 있고, 이 파일은 '무슨 말로 쓸지'만 갖는다.
관리자는 Settings 화면(문구 편집 모달)에서 각 항목을 덮어쓸 수 있으며,
덮어쓴 값만 `config.FIT_MESSAGES`에 담겨 data/settings.json에 영속화된다.
(전체를 저장하지 않는 이유 — 저장해 두면 이후 코드에서 기본 문구를 개선해도
 settings.json이 계속 옛 문장을 덮어써 개선이 반영되지 않는다.)

문구 규칙(요약) — 자세한 근거는 `.claude/rules/vector-db.md`:
  1. 문장은 근거만 말한다. 판정은 FIT_FLAG가 하므로 행동 지시("직접 선택하세요") 금지.
  2. 숫자는 조회 범위 안의 실측만. 비율(%)로 바꾸지 말 것.
  3. 약한 근거는 안 붙인다. '모두'는 3건 이상에서만.
  4. 계정명은 첫 문장에 한 번({a} 자리).
  5. 같은 종결을 3연속 쓰지 않는다(head/tail 두 벌을 두는 이유).
  6. 같은 결론을 가리키는 두 사실에 역접('반면','하지만')을 달지 않는다 —
     독자가 없는 대비 축을 찾다가 문장을 놓친다.
  7. 건수를 둘 이상 나열하면 합이 분모와 맞는지 본다. 안 맞으면 '등'이나
     '~ 중에는'·'섞여'로 나머지가 있음을 밝힌다(안 밝히면 사용자가 셈을 못 맞춘다).
  8. 유사성 표현은 '비슷하다' 계열로 통일한다 — '가까운'은 시간(최근)으로,
     '겹치는'은 중복으로 오독되고, '닮은'은 거래 서술에 어색하다.
  9. 이력 부재는 '이 계정으로 처리한' 한정을 붙인다 — 무한정 '이력은 없습니다'는
     같은 거래 상대가 다른 계정으로 있을 때 거짓으로 읽힌다.
  ※ 유사도(%)·점수 등 내부 지표는 어떤 문구에도 노출하지 않는다.

조사·미세 토큰('로/으로', '도/이', '등')은 문구가 아니라 문법 규칙이라 코드가 계산한다.
"""
from string import Formatter
from typing import Dict, List

import modules.recommend.config as cfg

# 문구 그룹 — 편집 모달의 탭
GROUPS = [
    ("axis", "축 용어", "form_type별 호칭. 여러 문장에 {치환}되어 들어간다"),
    ("piece", "근거 조각", "조합해서 한 문장을 이루는 부품. head=첫 문장, tail=뒤 문장"),
    ("verdict", "판정 문장", "그 자체로 FIT_REASON 전체가 되는 완성 문장"),
    ("fallback", "예외 경로", "스코어링 이전에 끝나거나 이름이 없을 때 쓰는 표현"),
]

# (키, 그룹, 기본 문구, 설명, {플레이스홀더: 미리보기 샘플값})
#   vars는 '허용 플레이스홀더 목록'이자 '미리보기 샘플값' 겸용 — 목록을 두 벌 관리하지 않는다.
_TABLE = [
    # ---------------- 축 용어 ----------------
    ("axis.CD.party_word", "axis", "가맹점",
     "CD 거래 상대 호칭. '이 {가맹점} 거래를 이 계정으로 처리한 이력은 없지만…' 처럼 쓰인다", {}),
    ("axis.CD.pay_word", "axis", "같은 카드",
     "CD 결제수단 조각 라벨. '{같은 카드} 거래 8건 중 6건을…'", {}),
    ("axis.CD.none_word", "axis", "같은 카드나 같은 가맹점",
     "CD에서 강한 근거가 없을 때 '… 이력에서는 뚜렷한 근거를 찾지 못했습니다'의 주어. "
     "가운뎃점(카드·가맹점)은 and/or가 모호해 '나'로 푼다", {}),
    ("axis.CD.sim_word", "axis", "가맹점명·업종이 비슷하게 적힌",
     "CD 벡터 유사도를 사용자 말로 옮긴 표현. '비슷한 거래'라 단정하지 말 것 — "
     "임베딩이 보장하는 건 텍스트가 비슷하게 적혔다는 데까지라 '적힌'으로 층위를 남긴다", {}),
    ("axis.ET.party_word", "axis", "거래처",
     "ET 거래 상대 호칭", {}),
    ("axis.ET.none_word", "axis", "같은 거래처",
     "ET에서 강한 근거가 없을 때 '… 이력에서는 뚜렷한 근거를 찾지 못했습니다'의 주어", {}),
    ("axis.ET.sim_word", "axis", "거래처명·담당자가 비슷하게 적힌",
     "ET 벡터 유사도를 사용자 말로 옮긴 표현", {}),

    # ---------------- 근거 조각 ----------------
    ("share.all.head", "piece", "{label}거래 {n}건을 모두 {a} 처리했습니다",
     "코호트 전부가 이 계정일 때(3건 이상) — 첫 문장",
     {"label": "'스타벅스' ", "n": "12", "a": "'복리후생비'로"}),
    ("share.all.tail", "piece", "{label}거래 {n}건도 모두 같은 계정입니다",
     "위와 같은 상황이지만 두 번째 이후 문장으로 붙을 때",
     {"label": "같은 카드 ", "n": "9"}),
    ("share.part.head", "piece", "{label}거래 {n}건 중 {same}건을 {a} 처리했습니다",
     "코호트 일부가 이 계정일 때 — 첫 문장",
     {"label": "'스타벅스' ", "n": "12", "same": "9", "a": "'복리후생비'로"}),
    ("share.part.tail", "piece", "{label}거래 {n}건 중 {same}건도 같은 계정입니다",
     "위와 같은 상황이지만 두 번째 이후 문장으로 붙을 때",
     {"label": "같은 카드 ", "n": "9", "same": "7"}),

    ("widen.all", "piece", "{label} 넓혀 봐도 {n}건 모두 같은 계정입니다",
     "부서·업종처럼 앞 조각의 상위 집합인 보조 근거(전부 일치). "
     "'넓혀 봐도'를 빼면 독립 근거가 하나 더 있는 것처럼 읽혀 건수가 합산돼 보인다",
     {"label": "같은 부서(경영지원팀)로", "n": "21"}),
    ("widen.part", "piece", "{label} 넓혀 봐도 {n}건 중 {same}건이 같은 계정입니다",
     "부서·업종 보조 근거(일부 일치)",
     {"label": "같은 부서(경영지원팀)로", "n": "21", "same": "15"}),

    ("party.one.head", "piece", "{label}거래 1건을 {a} 처리한 이력이 있습니다",
     "거래 상대 이력이 딱 1건일 때 — 첫 문장. 뒤 문장 버전은 없다 — "
     "party 조각은 항상 첫 조각이라 tail이 노출될 경로가 없다",
     {"label": "'스타벅스' ", "a": "'복리후생비'로"}),

    ("knn.head", "piece", "이 증빙과 가장 비슷한 과거 거래 {n}건을 모두 {a} 처리했습니다",
     "최근접 이웃이 전부 이 계정일 때(조각 중 가장 강한 근거) — 첫 문장. "
     "{n}은 유사도 1위부터 이 계정이 연속으로 이어지는 실제 길이(core.knn_run) — "
     "건마다 달라진다. 직접 숫자로 쓰지 말 것: 하한(FITNESS_KNN_K=3)을 박아 넣으면 "
     "어떤 건을 봐도 '3건'이라 근거가 템플릿으로 읽혀 신뢰도가 깎인다. "
     "'가까운'은 시간(최근)으로 오독돼 '비슷한'으로 쓴다(규칙 8)",
     {"n": "7", "a": "'복리후생비'로"}),
    ("knn.tail", "piece", "이 증빙과 가장 비슷한 과거 거래 {n}건도 모두 같은 계정입니다",
     "최근접 이웃 조각 — 뒤 문장", {"n": "7"}),

    ("label.party.named", "piece", "'{name}' ",
     "거래 상대 라벨(이름 있음). 뒤에 '거래'가 바로 붙으므로 끝 공백을 지우지 말 것",
     {"name": "스타벅스"}),
    ("label.party.unnamed", "piece", "같은 {party_word} ",
     "거래 상대 라벨(이름 없음). 다른 문구가 전부 '같은 ~'이라 '동일'을 쓰지 않는다",
     {"party_word": "가맹점"}),
    ("label.dept.named", "piece", "같은 부서({name})로",
     "부서 조각 라벨(이름 있음). '넓혀 봐도' 앞에 붙는다", {"name": "경영지원팀"}),
    ("label.dept.unnamed", "piece", "같은 부서로",
     "부서 조각 라벨(이름 없음)", {}),
    ("label.industry.named", "piece", "같은 업종({name}) ",
     "업종 조각 라벨(첫 문장용, 이름 있음)", {"name": "커피전문점"}),
    ("label.industry.unnamed", "piece", "같은 업종 ",
     "업종 조각 라벨(첫 문장용, 이름 없음)", {}),
    ("label.industry.widen.named", "piece", "같은 업종({name}){josa}",
     "업종 조각 라벨(뒤 문장용, 이름 있음). {josa}는 받침에 따라 로/으로가 자동 선택된다",
     {"name": "커피전문점", "josa": "으로"}),
    ("label.industry.widen.unnamed", "piece", "같은 업종으로",
     "업종 조각 라벨(뒤 문장용, 이름 없음)", {}),
    ("label.overall.head", "piece", "{sim_word} 과거 ",
     "거래 상대 근거가 없을 때의 폴백 라벨(첫 문장용)",
     {"sim_word": "가맹점명·업종이 비슷하게 적힌"}),
    ("label.overall.widen", "piece", "{sim_word} 거래 전체로",
     "거래 상대 근거가 없을 때의 폴백 라벨(뒤 문장용)",
     {"sim_word": "가맹점명·업종이 비슷하게 적힌"}),

    ("scope.prefix", "piece", "검색된 {head}",
     "첫 조각에 한 번만 붙는 범위 표시. 건수가 전체 통계로 오해되는 것을 막는다",
     {"head": "'스타벅스' 거래 12건을 모두 '복리후생비'로 처리했습니다"}),
    ("industry.prefix", "piece", "이 {party_word} 거래를 이 계정으로 처리한 이력은 없지만, {head}",
     "업종 조각이 첫 문장일 때의 한정. 업종은 '이 가게가 그렇다'가 아니라 "
     "'이런 가게는 보통 그렇다'는 일반론이라 같은 강도로 읽히면 안 된다. "
     "'이 계정으로 처리한'이 없으면 같은 가맹점 거래가 다른 계정으로만 있는 "
     "경우(same=0)에 거짓으로 읽힌다(규칙 9)",
     {"party_word": "가맹점",
      "head": "같은 업종(커피전문점) 거래 30건 중 24건을 '복리후생비'로 처리했습니다"}),

    ("note.stale", "piece", "{ym}을 마지막으로 같은 계정으로 처리한 거래가 없습니다",
     "검색결과 최신월보다 이 계정만 뒤처질 때의 경고(계약종료·조직개편·카드해지 신호). "
     "{ym}은 이 계정의 마지막 사용월이라 '이후로는'은 당월 포함 여부가 모호했다 — "
     "'을 마지막으로'는 경계가 없다. "
     "'다만'을 붙이지 말 것 — 경쟁 계정 문구도 '다만'으로 시작해 둘이 겹친다",
     {"ym": "2025년 8월"}),
    ("note.rival", "piece", "다만 {rival} 처리한 건{josa} {rival_n}건 섞여 있습니다",
     "추천은 유지하되 경쟁 계정이 있음을 밝히는 꼬리 문장. "
     "{josa}는 이 계정이 더 많으면 '도', 동률·역전이면 '이'로 자동 선택된다. "
     "'섞여'가 부분집합 표시다 — 없으면 첫 문장의 'N건 중 M건'과 이 건수의 합이 "
     "분모와 안 맞아 사용자가 셈을 못 맞춘다(규칙 7)",
     {"rival": "'여비교통비'로", "josa": "도", "rival_n": "3"}),

    # ---------------- 판정 문장 ----------------
    ("why.top", "verdict", "{acct}{josa} {freq}건으로 가장 많습니다",
     "근거가 얇은 경로에서 '그럼 왜 이 계정인가'에 답하는 절 — 검색결과 안에서 최다일 때. "
     "{josa}는 받침에 따라 이/가가 자동 선택된다 — '가'를 하드코딩하면 '이 계정' 폴백과 "
     "받침 계정명('상여금')에서 비문이 된다",
     {"acct": "'복리후생비'", "josa": "가", "freq": "34"}),
    ("why.plain", "verdict", "{freq}건이 {acct}입니다",
     "위와 같지만 최다가 아닐 때. SCORE 1위와 건수 1위는 다르므로 "
     "확인 없이 '가장 많다'고 쓰면 거짓이 된다",
     {"freq": "12", "acct": "'복리후생비'"}),

    ("hold.no_similar", "verdict",
     "이 증빙과 뚜렷하게 비슷한 과거 거래를 찾지 못했습니다. "
     "대신 {sim_word} 과거 거래 {total}건 중 {why}",
     "비슷한 정도가 낮고 강한 근거도 없을 때(검토). 강등 사유는 '건수가 적다'가 아니라 "
     "'비슷한 정도가 낮다'다 — 뒤에 나오는 건수와 모순되지 않게 쓸 것",
     {"sim_word": "가맹점명·업종이 비슷하게 적힌", "total": "187",
      "why": "12건이 '복리후생비'입니다"}),
    ("hold.no_strong", "verdict",
     "{sim_word} 과거 거래 {total}건 중 {why}. "
     "다만 {none_word} 이력에서는 뚜렷한 근거를 찾지 못했습니다",
     "비슷한 거래는 있지만 독립 근거(코드필드 일치)가 하나도 없을 때(검토). "
     "'이력은 없습니다'로 단정하면 거짓이 되는 경로가 있다 — 같은 가맹점 거래가 "
     "다른 계정으로만 있거나(same=0), 같은 카드 이력이 쏠림 미달로 근거에서 빠진 경우(규칙 9)",
     {"sim_word": "가맹점명·업종이 비슷하게 적힌", "total": "187",
      "why": "'복리후생비'가 34건으로 가장 많습니다", "none_word": "같은 카드나 같은 가맹점"}),
    ("hold.rival_split", "verdict",
     "검색된 {label}거래 {n}건은 {acct} {same}건, {rival} {rival_n}건{etc}으로 계정이 갈립니다",
     "같은 거래 상대를 여러 계정이 나눠 쓸 때(검토). 두 건수를 나란히 놓으면 "
     "'갈린다'는 사실 자체가 보류 사유로 읽힌다. {etc}는 3개 계정 이상일 때 ' 등'이 들어간다",
     {"label": "'스타벅스' ", "n": "9", "acct": "'복리후생비'", "same": "4",
      "rival": "'여비교통비'", "rival_n": "3", "etc": " 등"}),
    ("hold.party_one", "verdict",
     "검색된 {label}거래는 {a} 처리한 1건이 전부입니다. "
     "이 증빙과 가장 비슷한 과거 거래 {knn_n}건 중 같은 계정도 {knn_same}건이라 "
     "근거로 삼기엔 부족합니다{rival_txt}",
     "거래 상대 이력이 1건뿐이고 최근접 이웃도 이 계정이 아닐 때(검토). "
     "이 경로는 코호트가 정확히 1건(그 1건이 이 계정)일 때만 온다 — '거래 중 ~ 1건뿐'은 "
     "여러 건 중 1건만 이 계정이라는 함의라 사실과 반대로 읽혀 '1건이 전부'로 쓴다. "
     "두 사실은 '근거가 얇다'는 같은 결론을 가리키므로 역접('반면')을 쓰지 말 것 — "
     "독자가 없는 대비 축을 찾게 된다. 조사 '도'가 방향이 같음을 표시하고, "
     "판정 사유('부족합니다')를 문장 안에 둬야 숫자만 읽고 끝나지 않는다. "
     "{knn_n}을 숫자로 고정하면 검색결과가 그보다 적을 때 없는 거래를 근거로 삼는다",
     {"label": "'스타벅스' ", "a": "'복리후생비'로", "knn_n": "3", "knn_same": "0",
      "rival_txt": " (그 외에는 '여비교통비'가 2건으로 가장 많습니다)"}),
    ("hold.party_one.rival", "verdict",
     " (그 외에는 {rival}{josa} {rival_n}건으로 가장 많습니다)",
     "위 문장에 붙는 경쟁 계정 조각. 최근접 이웃에 다른 계정이 있을 때만 들어간다. "
     "나열 형식(', {rival} {rival_n}건')으로 쓰면 두 건수의 합이 분모와 안 맞아 "
     "('3건 중 0건, 2건') 사용자가 셈을 못 맞춘다. 그렇다고 무한정 '가장 많다'고 "
     "쓰면 동률(같은 계정 1건 : 경쟁 1건)에서 거짓이 된다 — `_fit_rival`은 "
     "**이 계정을 제외한** 최다를 주므로 '그 외에는'이라는 한정이 필수다. "
     "이전 표현 '다른 계정 중에는'은 이름 없는 경쟁 계정이 '다른 계정'으로 표기될 때 "
     "같은 말이 두 번 반복됐다. {josa}는 받침에 따라 이/가가 자동 선택된다",
     {"rival": "'여비교통비'", "josa": "가", "rival_n": "2"}),
    ("hold.low_conf", "verdict", "{head}. 다만 {rival}일 가능성도 비슷하게 높습니다",
     "거래 상대 근거 없이 업종·지배율로만 추천했는데 2위와 접전일 때(검토). "
     "'점수'·'유사도' 같은 내부 용어를 쓰지 말 것",
     {"head": "이 가맹점 거래를 이 계정으로 처리한 이력은 없지만, "
              "같은 업종(커피전문점) 거래 30건 중 18건을 '복리후생비'로 처리했습니다",
      "rival": "'여비교통비'"}),

    # ---------------- 예외 경로 ----------------
    ("word.this_account", "fallback", "이 계정",
     "계정명(HKONT_TXT)이 비어 있을 때 추천 계정을 가리키는 말. "
     "계정 코드를 노출하지 않기 위한 대체어 — 사용자에게 코드는 근거가 아니라 노이즈다", {}),
    ("word.other_account", "fallback", "다른 계정",
     "계정명이 비어 있을 때 경쟁 계정을 가리키는 말", {}),
    ("msg.no_result", "fallback",
     "이 증빙과 비슷한 과거 거래를 찾지 못해 추천할 계정이 없습니다.",
     "검색 결과가 없어 추천 계정 자체를 못 낸 경우(FIT_FLAG=3)", {}),
    ("msg.not_in_candidates", "fallback",
     "선택한 계정으로 처리한 과거 거래를 찾지 못했습니다.",
     "check-score에서 사용자가 고른 계정이 추천 후보에 없을 때(FIT_FLAG=3)", {}),
    ("msg.error", "fallback",
     "일시적인 오류로 이 증빙의 추천을 계산하지 못했습니다.",
     "배치 중 이 건만 예외로 건너뛴 경우(FIT_FLAG=3). msg.no_result와 반드시 구분할 것 — "
     "내부 오류를 '과거 거래가 없다'고 쓰면 데이터 탓으로 돌리는 거짓 사유가 SAP에 남고, "
     "나중에 서버 로그와 대조할 단서도 사라진다", {}),
]

FIT_MSG_DEFAULTS: Dict[str, str] = {k: d for k, _g, d, _desc, _v in _TABLE}
FIT_MSG_META: Dict[str, dict] = {
    k: {"group": g, "desc": desc, "vars": v} for k, g, _d, desc, v in _TABLE
}


def fit_msg(key: str, **kw) -> str:
    """문구 렌더 — 관리자 오버라이드 우선, 실패하면 기본값.

    try/except는 검증을 통과한 뒤에도 남긴다: settings.json을 손으로 고치는 경로가
    있고, 여기서 예외가 나면 추천 API 전체가 500이 된다."""
    tpl = cfg.FIT_MESSAGES.get(key) if isinstance(cfg.FIT_MESSAGES, dict) else None
    if tpl:
        try:
            return tpl.format(**kw)
        except Exception as e:
            cfg.logger.warning(f"FIT_MESSAGES['{key}'] 렌더 실패 → 기본 문구 사용: {e}")
    return FIT_MSG_DEFAULTS[key].format(**kw)


MAX_TPL_LEN = 300   # 가장 긴 기본 문구가 100자 남짓 — 오타·붙여넣기 사고 차단용 상한


def validate_fit_messages(overrides) -> List[str]:
    """오버라이드 dict 검증 → 오류 메시지 목록(빈 목록이면 통과).

    관리자 입력이 그대로 `.format()`에 들어가므로 여기가 신뢰 경계다.
    Formatter().parse는 `{a.__class__}` 같은 속성 접근도 필드명으로 뽑아 주므로
    화이트리스트 비교만으로 함께 차단된다."""
    if not isinstance(overrides, dict):
        return ["FIT_MESSAGES는 객체(키-문구 쌍)여야 합니다."]

    errs: List[str] = []
    for key, tpl in overrides.items():
        if key not in FIT_MSG_DEFAULTS:
            errs.append(f"알 수 없는 문구 키: {key}")
            continue
        if not isinstance(tpl, str) or not tpl.strip():
            errs.append(f"{key}: 문구를 비워 둘 수 없습니다.")
            continue
        if len(tpl) > MAX_TPL_LEN:
            errs.append(f"{key}: 문구가 너무 깁니다 ({len(tpl)}자 / 최대 {MAX_TPL_LEN}자).")
            continue
        try:
            fields = [(f, spec, conv) for _lit, f, spec, conv in Formatter().parse(tpl)
                      if f is not None]
        except ValueError as e:
            errs.append(f"{key}: 중괄호 짝이 맞지 않습니다 ({e}).")
            continue
        # 서식 지정자는 화이트리스트가 못 보는 자리다. `{n:>50000000}`는 필드명이
        # 허용값이라 통과한 뒤 렌더에서 5천만 자를 만들고, `{n:>{a}}`처럼 spec 안에
        # 중첩된 이름은 검사도 안 된 채 렌더에서 KeyError로 떨어진다.
        # 근거 문장에 정렬·자릿수를 쓸 일이 없으므로 통째로 막는다.
        if any(spec or conv for _f, spec, conv in fields):
            errs.append(f"{key}: 서식 지정자(':' 또는 '!')는 문구에 쓸 수 없습니다.")
            continue
        names = {f for f, _spec, _conv in fields}
        allowed = set(FIT_MSG_META[key]["vars"])
        bad = sorted(names - allowed)
        if bad:
            usable = ", ".join("{" + a + "}" for a in sorted(allowed)) or "없음"
            errs.append(
                f"{key}: 사용할 수 없는 항목 "
                + ", ".join("{" + b + "}" for b in bad)
                + f" (사용 가능: {usable})"
            )
    return errs


def strip_defaults(overrides: dict) -> dict:
    """기본값과 같은 항목은 저장하지 않는다 — 코드 기본 문구가 개선될 때 자동 반영되도록."""
    return {k: v for k, v in overrides.items() if v != FIT_MSG_DEFAULTS.get(k)}


if __name__ == "__main__":
    # 검증기 자체 점검 — `py -m app.fit_messages` (무거운 의존성 없는 모듈이라 그냥 돈다).
    # 여기가 관리자 입력의 신뢰 경계라, 화이트리스트가 새면 조용히 통과한다.
    for tpl in ("{a.__class__}", "{a[0]}", "{n:>99999999}", "{n:>{a}}", "{a!r}",
                "{unknown}", "{a", "", "   ", "가" * (MAX_TPL_LEN + 1)):
        assert validate_fit_messages({"share.part.head": tpl}), f"통과해선 안 됨: {tpl[:20]!r}"
    assert validate_fit_messages({"없는키": "x"})
    assert validate_fit_messages("dict 아님")
    assert not validate_fit_messages({"share.part.head": "{label}거래 {n}건 중 {same}건은 {a}"})
    assert not validate_fit_messages({}), "빈 dict는 전체 기본값 복원이라 통과해야 함"

    # 기본 문구는 각자의 vars(=샘플값)만으로 전부 렌더돼야 한다
    for k, m in FIT_MSG_META.items():
        FIT_MSG_DEFAULTS[k].format(**m["vars"])

    # 오버라이드가 깨져도 추천 API가 500이 되지 않고 기본값으로 떨어져야 한다
    cfg.FIT_MESSAGES = {"why.top": "{없는항목}"}
    assert fit_msg("why.top", acct="'A'", josa="가", freq=3) == FIT_MSG_DEFAULTS["why.top"].format(
        acct="'A'", josa="가", freq=3)
    cfg.FIT_MESSAGES = {}
    # 콘솔이 cp949라 em dash 같은 기호는 쓰지 않는다
    print(f"OK: 문구 {len(FIT_MSG_DEFAULTS)}개 / 검증기 정상")
