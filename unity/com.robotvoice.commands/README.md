# Robot Voice Commands

> 학교 과제로 만든 패키지입니다. 학습과 시연을 위한 것입니다.

플레이어가 한국어로 말한 명령을 로봇 명령 목록으로 변환하는 Unity 패키지입니다.

## 설치
**Window → Package Manager → + → Add package from tarball…**에서 `com.robotvoice.commands-0.1.1.tgz`를 선택하십시오.
예시 스크립트는 Package Manager에서 이 패키지 → **Samples → Example → Import**로 가져올 수 있습니다.

**첫 Play 때 음성 AI를 한 번 자동으로 설치합니다.** 인터넷 연결이 필요하며 10분 안팎이 걸립니다(Console에 "음성 AI 설치 중…"이 표시됩니다). 이후에는 수십 초 안에 준비됩니다. 시연 PC에서는 미리 한 번 Play해 두십시오.
게임을 빌드하면 음성 AI도 함께 포함됩니다. 빌드한 게임을 처음 실행할 때도 같은 설치가 한 번 진행됩니다.

## 사용
1. 빈 GameObject에 **VoiceCommands** 컴포넌트를 추가하십시오.
2. 명령을 받을 스크립트에서 이벤트를 구독하십시오.

```csharp
public VoiceCommands voice;

void OnEnable()  { voice.OnCommands += Handle; }
void OnDisable() { voice.OnCommands -= Handle; }

void Handle(VoiceResult result)
{
    foreach (VoiceCommand command in result.commands)
    {
        switch (command.op)
        {
            case "Select": /* command.id 로봇 선택 */ break;
            case "Move":   /* command.direction 으로 command.amount 만큼 이동 */ break;
            // Rotate, Interact, ResetGame, ExitGame
        }
    }
}
```

Play를 누르고 말하십시오. 말을 멈추고 **1.2초 동안 조용하면** 명령이 전달됩니다. 생각하는 동안에는 "음…" 하고 소리를 이어 주십시오.

## 명령
`result.commands`를 순서대로 실행하면 됩니다. `result.text`는 인식한 문장입니다.

| op | 사용하는 필드 | 의미 |
|---|---|---|
| `Select` | `id`: `red` / `green` / `blue` | 이후 명령을 받을 로봇 |
| `Move` | `direction`: `Front` / `Back` / `Left` / `Right`, `amount` | 로봇이 바라보는 방향 기준 이동 |
| `Rotate` | `way`: `Left` / `Right`, `amount` (도) | 회전 |
| `Interact` | | 벽 부수기 |
| `ResetGame` | | 퍼즐 초기화 |
| `ExitGame` | | 게임 종료 |

- `amount`가 **-1**이면 숫자를 말하지 않은 것입니다. 기본값은 게임에서 정하십시오.
- `Select`는 로봇이 바뀔 때만 전달됩니다. 처음부터 로봇 이름이 없으면 현재 선택된 로봇에 적용하십시오.

## 상태와 오류
- `OnStateChanged`: `Starting`(준비 중) → `Waiting`(대기) → `Recording`(듣는 중) → `Processing`(처리 중). 화면에 "듣는 중…" 같은 표시를 할 때 사용하십시오.
- `OnError`: 문제가 생기면 메시지가 전달됩니다. 음성 AI 준비에 실패하면 `%LOCALAPPDATA%\RobotVoice\ai.log` 파일에 원인이 기록됩니다.

## 말소리 감지가 잘 되지 않을 때
Inspector에서 `Log Level`을 켜면 Console에 소리 크기가 출력됩니다. 조용할 때보다 높고 말할 때보다 낮게 `Start Level`(기본 0.02)을 조정하십시오. 말이 너무 빨리 끊기면 `Silence Seconds`를 늘리십시오.

## 주의
- **Player Settings → Scripting Backend는 Mono(기본값)**로 두십시오. IL2CPP에서는 동작하지 않습니다.
- 처음 실행할 때 마이크 권한을 요청하면 허용하십시오.
