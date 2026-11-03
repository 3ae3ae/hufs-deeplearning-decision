"""sentences.jsonl 문장을 하나씩 보여주고 recordings/<번호>.wav 로 녹음한다 (16kHz 모노).

사용법: python3 record.py [마이크]     예) python3 record.py :2
마이크 번호 확인: ffmpeg -f avfoundation -list_devices true -i ""
"""
import json
import subprocess
import sys
import termios
from pathlib import Path

here = Path(__file__).parent
out = here / "recordings"
out.mkdir(exist_ok=True)
# shortcut: 이 맥에서 확인한 마이크 번호(:1 = MacBook Pro 마이크), 마이크가 바뀌면 인자로 지정
mic = sys.argv[1] if len(sys.argv) > 1 else ":1"

for line in (here / "sentences.jsonl").read_text(encoding="utf-8").splitlines():
    s = json.loads(line)
    wav = out / f"{s['id']}.wav"
    if wav.exists():  # 다시 녹음하려면 그 파일을 지우고 다시 실행
        continue
    print(f"\n[{s['id']}] {s['text']}")
    termios.tcflush(sys.stdin, termios.TCIFLUSH)  # q 뒤에 누른 Enter가 다음 녹음을 바로 시작시키지 않게
    input("  Enter → 녹음 시작, 다 읽으면 q ")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "avfoundation", "-i", mic,
                    "-ac", "1", "-ar", "16000", str(wav)], check=True)

print("\n전부 녹음했어요.")
