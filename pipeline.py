import re
from functools import cache


QUESTIONS = {
    "robot": {"type": "choice", "instructions": "⟦ ⟧ 안 조각에서 부른 로봇은? 이름이 없으면 none.",
              "criteria": {"red": "빨강이, 빨간 로봇, 레드", "green": "초록이, 초록 로봇, 그린", "blue": "파랑이, 파란 로봇, 블루", "none": "로봇 이름 없음"}},
    "action": {"type": "choice", "instructions": "⟦ ⟧ 안 조각에서 끝나는 명령은? 뒤에서 취소하거나 고쳐 말했으면 none.",
               "criteria": {"Move": "이동 (가, 이동해, 전진, 후진)", "Rotate": "회전 (돌아, 회전해, 돌려)", "Interact": "상호작용 (벽 부숴)",
                            "ResetGame": "퍼즐 처음부터 다시", "ExitGame": "게임 종료", "none": "명령이 끝나지 않음, 취소됨, 명령 아님"}},
    "direction": {"type": "choice", "instructions": "그 명령의 방향은? 앞 조각에 나온 방향도 본다. 명령이 없거나 방향을 말하지 않았으면 none.",
                  "criteria": {"Front": "앞, 위, 전진", "Back": "뒤, 아래, 후진", "Left": "왼쪽, 좌측, 반시계", "Right": "오른쪽, 우측, 시계 방향", "none": "방향 없음"}},
}
_NATIVE = dict(zip(
    "한 두 세 석 네 넉 다섯 여섯 일곱 여덟 아홉 열 스무".split(),
    [1, 2, 3, 3, 4, 4, 5, 6, 7, 8, 9, 10, 20],
))
_NATIVE.update({"열" + word: 10 + n for word, n in list(_NATIVE.items()) if n < 10})
_DIGITS = {word: n for n, word in enumerate("일이삼사오육칠팔구", 1)}
_D = "[일이삼사오육칠팔구]"
_SINO = rf"(?:{_D}?백(?:{_D}?십)?{_D}?|{_D}?십{_D}?|{_D})"
_NUMBER = re.compile(
    r"(?<![가-힣])(?:" + "|".join(sorted(_NATIVE, key=len, reverse=True))
    + "|" + _SINO + r")(?= ?(?:칸|미터|m|도|걸음))"
)
# 이 단어들 앞에서 자른다: 로봇 이름(인식 실수형 포함), 방향, 벽. 인식이 뭉개져 어미가 사라진 경계도 잡기 위해서
_STARTS = re.compile("|".join(sorted(
    "빨강이 빨강 빨간 레드 블루 불루 블로 파랑이 파랑 파란 초록이 초록기 쪼록기 초록 그린 그리은".split()
    + "오른쪽 왼쪽 앞 뒤 위 아래 우측 좌측 전진 후진 반시계 시계 벽".split(),
    key=len, reverse=True,
)))


def normalize_numbers(text: str) -> str:
    def replace(match):
        word = match.group()
        if word in _NATIVE:
            return str(_NATIVE[word])
        total = digit = 0
        for char in word:
            if char in "십백":
                total += (digit or 1) * {"십": 10, "백": 100}[char]
                digit = 0
            else:
                digit = _DIGITS[char]
        return str(total + digit)

    return _NUMBER.sub(replace, text)


@cache
def _kiwi():
    from kiwipiepy import Kiwi
    return Kiwi()


def split(text: str) -> list[str]:
    cuts = {0, len(text)}
    for token in _kiwi().tokenize(text):
        if token.tag in {"EF", "EC", "MAJ"}:
            cuts.add(token.start + token.len)
        if token.tag == "MAJ":
            cuts.add(token.start)
    cuts.update(match.start() for match in _STARTS.finditer(text))
    cuts.update(match.end() for match in re.finditer(r"\S*[가와해줘아어고라요죠서](?=\s|$)", text))
    cuts.update(match.end() for match in re.finditer(r"[.,?!…]+", text))
    # "가 줘", "돌아 주시면", "돌아 봐", "주시고요"처럼 보조 동사나 '요' 앞에서는 자르지 않는다: 명령 하나가 갈라져 숫자가 떨어지지 않게
    cuts = {c for c in cuts if c in (0, len(text)) or not re.match(r"\s*(?:주|줘|줄|봐|보세요|볼래|요(?![가-힣]))", text[c:])}
    offsets = sorted(cuts)
    segments = []
    for start, end in zip(offsets, offsets[1:]):
        segment = re.sub(r"^[\s.,?!…;]+|[\s.,?!…;]+$", "", text[start:end])
        if segment:
            segments.append(segment)
    # 맨 끝의 "아/어/음"은 버린다: 인식기가 "돌아"를 "돌아 아"로 늘려 쓰는데, 모델이 이를 고쳐 말하기로 읽는다
    while segments and re.fullmatch(r"[아어음으]+", segments[-1]):
        segments.pop()
    return segments


def windows(text: str) -> list[tuple[str, str]]:
    segments, spans, cursor = split(text), [], 0
    for segment in segments:
        start = text.index(segment, cursor)
        spans.append((start, start + len(segment)))
        cursor = start + len(segment)
    return [
        (segment, text[spans[max(0, j - 2)][0]:start] + "⟦" + segment + "⟧"
         + text[end:spans[min(len(spans) - 1, j + 2)][1]])
        for j, (segment, (start, end)) in enumerate(zip(segments, spans))
    ]


def _amount(text: str, action: str):
    # 단위로 어느 명령의 숫자인지 가린다: 도는 회전, 칸·미터·걸음은 이동 (취소된 "2칸"이 뒤 회전에 붙지 않게)
    units = {"도", ""} if action == "Rotate" else {"칸", "미터", "m", "걸음", ""}
    found = [int(n) for n, unit in re.findall(r"(\d+) ?(칸|미터|m|걸음|도)?", text) if unit in units]
    return found[-1] if found else None


def assemble(segments) -> list[str]:
    commands = []
    current = selected = None
    previous = ""  # 바로 앞 조각이 명령 없는 조각이면 그 글: "오른쪽으로 3칸 | 가"처럼 숫자만 떨어진 경우
    for text, robot, action, direction in segments:
        if robot != "none":
            current = robot
        if action == "none":
            previous = text
            continue
        amount = _amount(text, action)
        if amount is None:
            amount = _amount(previous, action)
        amount = -1 if amount is None else amount
        previous = ""
        if action in {"ResetGame", "ExitGame"}:
            commands.append(f"{action}()")
            continue
        if current is not None and current != selected:
            commands.append(f'Select("{current}")')
            selected = current
        if action == "Interact":
            commands.append("Interact()")
        elif action == "Move":
            direction = direction if direction in {"Front", "Back", "Left", "Right"} else "Front"
            commands.append(f'Move("{direction}", {amount})')
        elif action == "Rotate":
            if direction == "Back":
                direction, amount = "Right", 180
            elif direction not in {"Left", "Right"}:
                direction = "Right"
            commands.append(f'Rotate("{direction}", {amount})')
    return commands
