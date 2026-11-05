# 로봇 음성 명령 AI

> **학교 과제로 만든 프로젝트입니다.** 퍼즐 게임 과제의 음성 명령 부분을 맡아 만든 것으로, 학습과 시연을 위한 것입니다. 실제 서비스에서의 사용은 고려하지 않았습니다.

플레이어의 한국어 음성을 로봇 명령 목록으로 변환합니다.

이 브랜치(`over-keyword`, Unity 패키지 0.2.0)는 말 끝에 **"오버"**라고 하면 바로 변환하는 버전입니다. 1.2초 동안 조용하면 변환하는 버전은 `main` 브랜치(Unity 패키지 0.1.1)에 있습니다.

```
음성 → SenseVoice(음성인식) → "오버" 확인 → 숫자 변환·조각 나누기 → Laya(조각마다 로봇/행동/방향) → 명령 목록
```
SenseVoice는 스트리밍 모델이 아니므로, 녹음하는 동안 지금까지의 소리 전체를 0.3초 간격으로 다시 인식해 "오버"를 찾습니다. "오버"가 나오기 전까지는 음성인식만 하고, "오버"가 나오면 그 앞의 문장만 명령으로 변환합니다. 조용해져도 변환하지 않으며, 말 사이의 긴 무음은 잘라 낸 채 "오버"가 나올 때까지 계속 듣습니다.

## Unity 패키지 만들기
```sh
uv run python build_unity_package.py   # → dist/com.robotvoice.commands-0.2.0.tgz (약 600MB)
```
Unity에서 *Add package from tarball*로 이 파일 하나만 설치하면 됩니다. 사용법은 패키지 안의 `README.md`(`unity/com.robotvoice.commands/README.md`)에 있습니다.
패키지는 첫 Play 때 uv, Python, 필요한 라이브러리(Windows는 GPU용), 음성인식 모델을 `%LOCALAPPDATA%\RobotVoice`에 설치하고, 이후 AI를 백그라운드에서 실행합니다. 설치 기록은 같은 폴더의 `ai.log`에 남습니다.
모델이나 AI 코드를 수정하면 `package.json`의 `version`을 올리고 다시 만드십시오.

## 개발용 명령
```sh
uv run python try_mic.py                                            # 마이크로 말해 보기 (말 끝에 "오버", 결과가 터미널에 출력됨)
uv run python asr_test/eval_audio.py --model models/laya-commands   # 실제 녹음 33개 평가
uv run python test_pipeline.py && uv run python test_server.py      # 테스트
uv run train_laya.py train --out models/새모델                      # 학습 (Apple Silicon, 약 2시간 30분)
uv run make_data.py                                                 # 학습 데이터 생성 (pi + neuralwatt 필요)
```
`main`에 푸시하면 GitHub Actions가 새 Windows 환경에서 설치와 평가를 확인합니다.

## 성능
- 실제 녹음 33개(음성부터 명령까지): **28/33**. 4개는 음성인식이 숫자를 잘못 인식하여 모델로 맞힐 수 있는 최대치는 29개입니다.
- 속도: Mac M4 Pro에서 평균 0.31초.
- "오버"를 말하고 명령이 나오기까지: Mac M4 Pro에서 약 0.3초(TTS 음성으로 측정, 다시 인식하는 간격 포함).

## 한계
- 음성인식이 숫자를 다른 숫자로 인식하면("사 미터"→"삼 미터") 바로잡을 수 없습니다.
- 28/33은 이 33문장의 오류를 보고 개선한 결과입니다. 새로 녹음한 문장으로 다시 평가해야 합니다.
- GPU 없이 Windows CPU로만 실행하면 몇 초씩 걸릴 수 있습니다. CPU에서는 음성인식 한 번에 0.5~0.7초가 걸려 "오버"를 늦게 알아챕니다.
- "오버" 인식은 TTS 음성으로만 시험했습니다. 실제 목소리로 다시 확인해야 합니다.
