# 로봇 음성 명령 AI

> **학교 과제로 만든 프로젝트예요.** 퍼즐 게임 과제의 음성 명령 부분을 맡아 만든 것으로, 학습과 시연용이에요. 실제 서비스에 쓰는 것은 고려하지 않았어요.

플레이어의 한국어 음성을 로봇 명령 목록으로 바꿔요.

```
음성 → SenseVoice(음성인식) → 숫자 변환·조각 나누기 → Laya(조각마다 로봇/행동/방향) → 명령 목록
```

## Unity 패키지 만들기
```sh
uv run python build_unity_package.py   # → dist/com.robotvoice.commands-0.1.1.tgz (약 600MB)
```
Unity에서 *Add package from tarball*로 이 파일 하나만 설치하면 돼요. 사용법은 패키지 안의 `README.md`(`unity/com.robotvoice.commands/README.md`)에 있어요.
패키지가 첫 Play 때 uv, Python, 필요한 라이브러리(Windows는 GPU용), 음성인식 모델을 `%LOCALAPPDATA%\RobotVoice`에 설치하고, 이후 AI를 백그라운드에서 켜요. 설치 기록은 같은 폴더의 `ai.log`에 남아요.
모델이나 AI 코드를 고치면 `package.json`의 `version`을 올리고 다시 만드세요.

## 개발용 명령
```sh
uv run python try_mic.py                                            # 마이크로 말해 보기 (결과가 터미널에 나와요)
uv run python asr_test/eval_audio.py --model models/laya-commands   # 실제 녹음 33개 평가
uv run python test_pipeline.py && uv run python test_server.py      # 테스트
uv run train_laya.py train --out models/새모델                      # 학습 (Apple Silicon, 약 2시간 반)
uv run make_data.py                                                 # 학습 데이터 생성 (pi + neuralwatt 필요)
```
`main`에 푸시하면 GitHub Actions가 깨끗한 Windows에서 설치와 평가를 확인해요.

## 성능
- 실제 녹음 33개(음성부터 끝까지): **28/33**. 4개는 음성인식이 숫자를 틀려서 모델로는 최대 29개예요.
- 속도: Mac M4 Pro에서 평균 0.31초.

## 한계
- 음성인식이 숫자를 다른 숫자로 바꾸면("사 미터"→"삼 미터") 바로잡을 수 없어요.
- 28/33은 이 33문장의 실수를 보고 고친 결과예요. 새로 녹음한 문장으로 다시 재야 해요.
- GPU 없이 Windows CPU로만 돌리면 몇 초씩 걸릴 수 있어요.
