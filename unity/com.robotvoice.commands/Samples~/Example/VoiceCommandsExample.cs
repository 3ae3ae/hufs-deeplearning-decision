using UnityEngine;

public class VoiceCommandsExample : MonoBehaviour
{
    [Tooltip("VoiceCommands가 붙은 오브젝트를 이 필드로 드래그하십시오.")]
    public VoiceCommands client;

    void OnEnable()
    {
        if (client == null)
        {
            Debug.LogError("Inspector에서 VoiceCommands를 연결하십시오.");
            return;
        }
        client.OnCommands += HandleCommands;
        client.OnStateChanged += HandleState;
        client.OnError += HandleError;
    }

    void OnDisable()
    {
        if (client == null) return;
        client.OnCommands -= HandleCommands;
        client.OnStateChanged -= HandleState;
        client.OnError -= HandleError;
    }

    void HandleCommands(VoiceResult response)
    {
        Debug.Log("인식한 말: " + response.text);
        foreach (VoiceCommand command in response.commands)
        {
            switch (command.op)
            {
                case "Select":
                    // 여기서 command.id에 해당하는 대상을 선택합니다.
                    Debug.Log("선택: " + command.id);
                    break;
                case "Move":
                    // 여기서 command.direction 방향으로 command.amount만큼 이동합니다.
                    Debug.Log("이동: " + command.direction + " / " + command.amount);
                    break;
                case "Rotate":
                    // 여기서 command.way 방향으로 command.amount도 회전합니다.
                    Debug.Log("회전: " + command.way + " / " + command.amount);
                    break;
                case "Interact":
                    // 여기서 선택한 대상과 상호작용합니다.
                    Debug.Log("상호작용");
                    break;
                case "ResetGame":
                    // 여기서 게임을 처음 상태로 되돌립니다.
                    Debug.Log("게임 초기화");
                    break;
                case "ExitGame":
                    // 여기서 게임을 종료합니다.
                    Debug.Log("게임 종료");
                    break;
            }
        }
    }

    void HandleState(VoiceCommands.State state) { Debug.Log("음성 상태: " + state); }
    void HandleError(string message) { Debug.LogError(message); }
}
