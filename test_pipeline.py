import json
from pathlib import Path

from pipeline import assemble, normalize_numbers, split, windows


sentences = {
    row["id"]: row
    for row in map(json.loads, (Path(__file__).parent / "asr_test/sentences.jsonl").read_text(encoding="utf-8").splitlines())
}

for text, expected in [
    ("두칸가", "2칸가"),
    ("세 칸", "3 칸"),
    ("열칸", "10칸"),
    ("다섯걸음", "5걸음"),
    ("삼십칠 도", "37 도"),
    ("백팔십 도", "180 도"),
    ("사십오 도", "45 도"),
    ("구십도", "90도"),
    ("이 미터", "2 미터"),
    ("한칸만가", "1칸만가"),
    ("열두 칸", "12 칸"),
    ("블루 앞으로 세 칸, 아니다 네 칸 가", "블루 앞으로 3 칸, 아니다 4 칸 가"),
    ("삼백육십도", "360도"),
    ("열아홉걸음 스무m", "19걸음 20m"),
    ("석칸 넉 칸", "3칸 4 칸"),
    ("한칸 두  칸 두\t칸", "1칸 두  칸 두\t칸"),
    ("(두칸) 3두칸", "(2칸) 32칸"),
]:
    assert normalize_numbers(text) == expected, text

for text in ["빨강이도 가", "이거 어떡하지", "한 강", "블루 3 칸", "오른쪽으로 돌아"]:
    assert normalize_numbers(text) == text, text

for text, starts in [
    (sentences["27"]["text"], ["블루는", "그리고", "앞으로 2", "오른쪽으로 20", "초록이는", "아니다", "위로 2", "빨강이는", "아래로 1"]),
    ("앞으로 2칸과 아삭한만 취소소 오른쪽으로 돌아", ["오른쪽으로 돌아"]),
    ("아 그러니까 초록기가 앞으로 1칸 가서 벽 부수고 음 다시 뒤로 1칸 와", ["벽 부수고", "뒤로 1칸 와"]),
    ("블루 왼쪽으로 돌아 앞으로 세칸가", ["블루", "앞으로 3칸가"]),
    ("빨강이 앞으로 가 아라 하지마", ["빨강이", "아라"]),
    ("오른쪽으로 20도 돌아쪼록기는는 오른쪽으로 아니다 돌지 말고", ["쪼록기는는"]),
    ("초록이 앞으로  독한 빨강이 뒤 로 한칸", ["빨강이"]),
    ("레드는 위로 색칸 가고 그리은 아래로 두칸가", ["그리은"]),
]:
    segments = split(normalize_numbers(text))
    for start in starts:
        assert any(segment.startswith(start) for segment in segments), (start, segments)

assert split(normalize_numbers("빨강이 앞으로 두 칸 가 줘")) == ["빨강이", "앞으로 2 칸 가 줘"]
assert split("게임 꺼 줘") == ["게임 꺼 줘"]
assert split("오른쪽으로 돌아아") == ["오른쪽으로 돌아"]
assert split("왼쪽 으로 30 도 돌아 아")[-1] == "왼쪽 으로 30 도 돌아"
assert split("아 이거 어떡하지")[0] == "아"
assert split("블루는 오른쪽으로 45 도 돌아 주시면 됩니다")[-2:] == ["오른쪽으로 45 도 돌아 주시면", "됩니다"]
assert assemble([(s, "none", "Rotate" if s == "됩니다" else "none", "Right")
                 for s in split("오른쪽으로 45 도 돌아 주시면 됩니다")]) == ['Rotate("Right", 45)']
assert split("파랑이는 뒤로 가 주시고요, 음, 그리고") == ["파랑이는", "뒤로 가 주시고요", "음", "그리고"]
assert split("오른쪽으로 90 도 돌아봐") == ["오른쪽으로 90 도 돌아봐"]
assert split(" . , ? ! … ; \n") == []
assert split("\u3000 ;빨강; \u3000") == ["빨강"]
assert split("빨강,블루;레드") == ["빨강", "블루", "레드"]

assert windows("빨강이 앞으로 2칸 가, 블루 왼쪽으로 돌아. 앞으로 가") == [
    ("빨강이", "⟦빨강이⟧ 앞으로 2칸 가, 블루"),
    ("앞으로 2칸 가", "빨강이 ⟦앞으로 2칸 가⟧, 블루 왼쪽으로 돌아"),
    ("블루", "빨강이 앞으로 2칸 가, ⟦블루⟧ 왼쪽으로 돌아. 앞으로 가"),
    ("왼쪽으로 돌아", "앞으로 2칸 가, 블루 ⟦왼쪽으로 돌아⟧. 앞으로 가"),
    ("앞으로 가", "블루 왼쪽으로 돌아. ⟦앞으로 가⟧"),
]
assert windows(" . , ? ! … ; \n") == []

assert assemble([
    ("빨강이는 오른쪽으로 3 미터 가고", "red", "Move", "Right"),
    ("블루는 왼쪽으로 30 도 돌아", "blue", "Rotate", "Left"),
    ("그리고", "none", "none", "none"),
    ("앞으로 2 미터 이동해", "none", "Move", "Front"),
    ("오른쪽으로 20 도 돌아", "none", "Rotate", "Right"),
    ("초록이는 오른쪽으로", "green", "none", "none"),
    ("아니다", "none", "none", "none"),
    ("돌지", "none", "none", "none"),
    ("말고", "none", "none", "none"),
    ("위로 2 칸만 이동해", "none", "Move", "Front"),
    ("그러고", "none", "none", "none"),
    ("빨강이는 아래로 1 칸", "red", "Move", "Back"),
]) == sentences["27"]["commands"]

assert assemble([
    ("앞으로 2칸 가", "none", "none", "Front"),
    ("아 잠깐 취소", "none", "none", "none"),
    ("오른쪽으로 돌아", "none", "Rotate", "Right"),
]) == ['Rotate("Right", -1)']

assert assemble([
    ("블루 오른쪽으로 180 도 돌고", "blue", "Rotate", "Right"),
    ("앞으로 5 칸 가", "none", "none", "Front"),
    ("아 아니다", "none", "none", "none"),
    ("4 칸", "none", "Move", "Front"),
    ("그리고", "none", "none", "none"),
    ("빨강이는 벽 부숴", "red", "Interact", "none"),
]) == sentences["29"]["commands"]

assert assemble([
    ("오른쪽으로 3칸", "none", "none", "Right"),
    ("가", "none", "Move", "Right"),
]) == ['Move("Right", 3)']

assert assemble([
    ("앞으로 2칸과 아삭한만 취소소", "none", "none", "none"),
    ("오른쪽으로 돌아", "none", "Rotate", "Right"),
]) == ['Rotate("Right", -1)']

assert assemble([
    ("오른쪽으로 90도", "none", "none", "Right"),
    ("돌아", "none", "Rotate", "Right"),
]) == ['Rotate("Right", 90)']

for segment, expected in [
    (("뒤로 돌아", "none", "Rotate", "Back"), 'Rotate("Right", 180)'),
    (("앞으로 가", "none", "Move", "Front"), 'Move("Front", -1)'),
    (("가", "none", "Move", "none"), 'Move("Front", -1)'),
    (("돌아", "none", "Rotate", "none"), 'Rotate("Right", -1)'),
]:
    assert assemble([segment]) == [expected], segment

assert assemble([
    ("다 망했다", "none", "none", "none"),
    ("리셋", "none", "ResetGame", "none"),
]) == ["ResetGame()"]

assert assemble([
    ("초록이 아 이", "green", "none", "none"),
    ("빨강이 뒤로 1칸가", "red", "Move", "Back"),
]) == ['Select("red")', 'Move("Back", 1)']

assert assemble([
    ("빨강이 앞으로 가", "red", "none", "Front"),
    ("아라", "none", "none", "none"),
    ("하지마", "none", "none", "none"),
]) == []

assert assemble([
    ("앞으로 2칸 가", "none", "Move", "Front"),
    ("오른쪽으로 돌아", "none", "Rotate", "Right"),
]) == ['Move("Front", 2)', 'Rotate("Right", -1)']

assert assemble([
    ("빨강이", "red", "none", "none"),
    ("1칸 가", "none", "Move", "Front"),
    ("벽 부숴", "none", "Interact", "none"),
    ("초록이", "green", "none", "none"),
    ("빨강이", "red", "none", "none"),
    ("게임 종료", "none", "ExitGame", "none"),
    ("돌아", "none", "Rotate", "Front"),
]) == ['Select("red")', 'Move("Front", 1)', "Interact()", "ExitGame()", 'Rotate("Right", -1)']
assert assemble([
    ("3칸", "none", "none", "none"),
    ("5칸에서 4칸 가", "none", "Move", "none"),
]) == ['Move("Front", 4)']
assert assemble([]) == []

print("pipeline tests passed")
