# Robot Voice Commands

> 학교 과제로 만든 패키지예요. 학습과 시연용이에요.

플레이어가 한국어로 말한 명령을 로봇 명령 목록으로 바꿔 주는 Unity 패키지예요.

## 설치
**Window → Package Manager → + → Add package from tarball…**에서 받은 `com.robotvoice.commands-0.1.1.tgz`를 고르세요.
예시 스크립트는 Package Manager에서 이 패키지 → **Samples → Example → Import**로 가져올 수 있어요.

**첫 Play 때 한 번 음성 AI를 자동으로 설치해요.** 인터넷이 필요하고 10분 안팎 걸려요(Console에 "음성 AI 설치 중…"이 보여요). 그다음부터는 수십 초 안에 준비돼요. 데모 PC에서는 미리 한 번 Play해 두세요.
게임을 빌드하면 음성 AI도 함께 들어가요. 빌드한 게임을 처음 켤 때도 같은 설치가 한 번 진행돼요.

## 사용
1. 빈 GameObject에 **VoiceCommands** 컴포넌트를 붙이세요.
2. 명령을 받을 스크립트에서 이벤트를 구독하세요.

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

Play를 누르고 말하세요. 말을 멈추고 **1.2초 동안 조용하면** 명령이 와요. 생각하는 동안에는 "음…" 하고 소리를 이어 주세요.

## 명령
`result.commands`를 순서대로 실행하면 돼요. `result.text`는 알아들은 문장이에요.

| op | 쓰는 칸 | 뜻 |
|---|---|---|
| `Select` | `id`: `red` / `green` / `blue` | 이후 명령을 받을 로봇 |
| `Move` | `direction`: `Front` / `Back` / `Left` / `Right`, `amount` | 로봇이 보는 방향 기준 이동 |
| `Rotate` | `way`: `Left` / `Right`, `amount` (도) | 회전 |
| `Interact` | | 벽 부수기 |
| `ResetGame` | | 퍼즐 처음 상태로 |
| `ExitGame` | | 게임 종료 |

- `amount`가 **-1**이면 숫자를 말하지 않은 거예요. 기본값은 게임에서 정해 주세요.
- `Select`는 로봇이 바뀔 때만 와요. 처음부터 로봇 이름이 없으면 지금 선택된 로봇에 적용하세요.

## 상태와 오류
- `OnStateChanged`: `Starting`(준비 중) → `Waiting`(대기) → `Recording`(듣는 중) → `Processing`(처리 중). 화면에 "듣는 중…" 같은 표시를 할 때 쓰세요.
- `OnError`: 문제가 생기면 메시지가 와요. 음성 AI 준비에 실패하면 `%LOCALAPPDATA%\RobotVoice\ai.log` 파일에 원인이 남아요.

## 말소리 감지가 잘 안 될 때
Inspector에서 `Log Level`을 켜면 Console에 소리 크기가 찍혀요. 조용할 때보다 높고 말할 때보다 낮게 `Start Level`(기본 0.02)을 맞추세요. 말이 너무 빨리 끊기면 `Silence Seconds`를 늘리세요.

## 주의
- **Player Settings → Scripting Backend는 Mono(기본값)**로 두세요. IL2CPP에서는 동작하지 않아요.
- 처음 실행할 때 마이크 권한을 물어보면 허용하세요.
