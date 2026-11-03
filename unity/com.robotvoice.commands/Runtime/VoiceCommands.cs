using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using Debug = UnityEngine.Debug;

[Serializable]
public class VoiceCommand
{
    public string op;
    public string id;
    public string direction;
    public string way;
    public int amount;
}

[Serializable]
public class VoiceResult
{
    public string text;
    public VoiceCommand[] commands;
}

public class VoiceCommands : MonoBehaviour
{
    public enum State { Starting, Waiting, Recording, Processing }
    public State CurrentState { get; private set; } = State.Waiting;
    public event Action<VoiceResult> OnCommands;
    public event Action<State> OnStateChanged;
    public event Action<string> OnError;

    [Tooltip("이 RMS 이상이면 말소리로 판단합니다. 주변 소음보다 높게 조정하세요.")]
    public float startLevel = 0.02f;
    [Tooltip("이 시간(초) 동안 조용하면 녹음을 끝냅니다.")]
    public float silenceSeconds = 1.2f;
    [Tooltip("한 번에 녹음할 최대 시간(초)입니다. 말하기 전 보관한 소리도 포함합니다.")]
    public float maxSeconds = 30f;
    [Tooltip("말하기 직전의 소리를 이 시간(초)만큼 보관해 첫 음절을 지킵니다.")]
    public float preRollSeconds = 0.3f;
    [Tooltip("현재 RMS를 초당 두 번 Console에 출력합니다. 말소리 기준 조정에 사용하세요.")]
    public bool logLevel = false;

    readonly Queue<float> preRoll = new Queue<float>();
    readonly List<float> recording = new List<float>();
    AudioClip clip;
    const string AiAddress = "http://127.0.0.1:8000";
    static readonly string Home = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RobotVoice");
    static readonly string LogPath = Path.Combine(Home, "ai.log");
    static readonly SemaphoreSlim SetupLock = new SemaphoreSlim(1, 1);
    static readonly object LogLock = new object();
    static bool Windows { get { return Path.DirectorySeparatorChar == '\\'; } }
    static string Python { get { return Windows ? Path.Combine(Home, "venv", "Scripts", "python.exe") : Path.Combine(Home, "venv", "bin", "python"); } }
    static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
    static Process ownedProcess;
    CancellationTokenSource lifetime;

    float[] chunk;
    int sampleRate, readPosition, chunkCount, preRollSamples, maxSamples, lastLoudSample;
    float nextLogTime, noiseLevel = -1f;

    [Serializable]
    class Health { public bool ok; }

    async void OnEnable()
    {
        lifetime = new CancellationTokenSource();
        CancellationToken token = lifetime.Token;
        SetState(State.Starting);
        try
        {
            Directory.CreateDirectory(Home);
            await EnsureReady(token);
            token.ThrowIfCancellationRequested();
            StartMicrophone();
            SetState(State.Waiting);
            if (!token.IsCancellationRequested) StartCoroutine(Listen());
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            if (!token.IsCancellationRequested)
            {
                AppendLog(error.ToString());
                Fail("음성 AI를 준비하지 못했습니다.");
            }
        }
    }

    async Task<bool> IsHealthy(CancellationToken token)
    {
        using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(token))
        {
            timeout.CancelAfter(1000);
            try
            {
                using (var response = await Http.GetAsync(AiAddress + "/health", timeout.Token))
                {
                    if (!response.IsSuccessStatusCode) return false;
                    Health health = JsonUtility.FromJson<Health>(await response.Content.ReadAsStringAsync());
                    return health != null && health.ok;
                }
            }
            catch (Exception)
            {
                token.ThrowIfCancellationRequested();
                return false;
            }
        }
    }

    static string AiFolder()
    {
#if UNITY_EDITOR
        var package = UnityEditor.PackageManager.PackageInfo.FindForAssembly(typeof(VoiceCommands).Assembly);
        if (package == null) throw new InvalidOperationException("음성 AI 패키지를 찾을 수 없습니다.");
        return Path.Combine(package.resolvedPath, "AI~");
#else
        return Path.Combine(Application.streamingAssetsPath, "RobotVoiceAI");
#endif
    }

    async Task EnsureReady(CancellationToken token)
    {
        if (await IsHealthy(token)) return;
        await SetupLock.WaitAsync(token);
        try
        {
            token.ThrowIfCancellationRequested();
            if (await IsHealthy(token)) return;
            if (ownedProcess == null || ownedProcess.HasExited)
            {
                string folder = AiFolder();
                using (var progress = CancellationTokenSource.CreateLinkedTokenSource(token))
                {
                    Task reporting = ReportProgress(progress.Token);
                    try { await Install(folder, token); }
                    finally { progress.Cancel(); await reporting; }
                }
                token.ThrowIfCancellationRequested();
                if (ownedProcess != null) ownedProcess.Dispose();
                ownedProcess = null;
                // shortcut: 프로세스 실행은 데스크톱 Mono 전용입니다. IL2CPP 지원 시 네이티브 실행기가 필요합니다.
                ownedProcess = StartProcess(Python, "server.py --model models/laya-commands", folder, out _);
                // 에디터에서는 다음 Play 때 바로 쓰도록 AI를 남깁니다.
#if !UNITY_EDITOR
                Application.quitting -= StopAI;
                Application.quitting += StopAI;
#endif
            }
        }
        finally { SetupLock.Release(); }

        Process process = ownedProcess;
        using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(token))
        {
            timeout.CancelAfter(180000);
            try
            {
                while (true)
                {
                    timeout.Token.ThrowIfCancellationRequested();
                    if (process.HasExited) throw new InvalidOperationException("음성 AI가 종료되었습니다.");
                    Task nextPoll = Task.Delay(1000, timeout.Token);
                    if (await IsHealthy(timeout.Token)) return;
                    await nextPoll;
                }
            }
            catch (OperationCanceledException)
            {
                token.ThrowIfCancellationRequested();
                throw new TimeoutException("음성 AI 준비 시간이 초과되었습니다.");
            }
        }
    }

    static async Task ReportProgress(CancellationToken token)
    {
        try
        {
            while (true)
            {
                Debug.Log("음성 AI 설치 중… (처음 한 번, 몇 분 걸려요)");
                await Task.Delay(30000, token);
            }
        }
        catch (OperationCanceledException) { }
    }

    static async Task Install(string folder, CancellationToken token)
    {
        string lockFile = Path.Combine(folder, "uv.lock");
        if (!File.Exists(Path.Combine(folder, "server.py")) || !File.Exists(lockFile) ||
            !File.Exists(Path.Combine(folder, "models", "laya-commands", "model.safetensors")))
            throw new InvalidOperationException("패키지에 음성 AI 파일이 없습니다.");
        string hash;
        using (var sha = SHA256.Create())
            hash = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(lockFile))).Replace("-", "").ToLowerInvariant();
        string marker = Path.Combine(Home, "installed.txt");
        if (File.Exists(marker) && File.ReadAllText(marker).Trim() == hash && File.Exists(Python)) return;

        string uvFolder = Path.Combine(Home, "uv");
        string uv = Path.Combine(uvFolder, Windows ? "uv.exe" : "uv");
        if (!File.Exists(uv))
        {
            string asset = Windows ? "uv-x86_64-pc-windows-msvc.zip" :
                RuntimeInformation.OSArchitecture == Architecture.Arm64 ? "uv-aarch64-apple-darwin.tar.gz" :
                "uv-x86_64-apple-darwin.tar.gz";
            string archive = Path.Combine(Home, "uv.download");
            await Download("https://github.com/astral-sh/uv/releases/download/0.13.6/" + asset, archive, token);
            if (Directory.Exists(uvFolder)) Directory.Delete(uvFolder, true);
            Directory.CreateDirectory(uvFolder);
            await RunStep("tar", "-xf " + Quote(archive) + " -C " + Quote(uvFolder), Home, token);
            string[] binaries = Directory.GetFiles(uvFolder, Windows ? "uv.exe" : "uv", SearchOption.AllDirectories);
            if (binaries.Length != 1) throw new InvalidOperationException("설치 도구를 찾을 수 없습니다.");
            if (binaries[0] != uv) File.Move(binaries[0], uv);
            File.Delete(archive);
        }
        await RunStep(uv, "sync --frozen --no-dev", folder, token);
        string downloadModel = "from funasr import AutoModel; AutoModel(model='FunAudioLLM/SenseVoiceSmall', hub='hf', disable_update=True)";
        await RunStep(Python, "-c " + Quote(downloadModel), folder, token);
        token.ThrowIfCancellationRequested();
        // 모델 다운로드가 실패하면 다음 Play에서 다시 시도합니다.
        File.WriteAllText(marker, hash);
    }

    static async Task Download(string url, string path, CancellationToken token)
    {
        using (var response = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, token))
        {
            response.EnsureSuccessStatusCode();
            using (var input = await response.Content.ReadAsStreamAsync())
            using (var output = File.Create(path))
                await input.CopyToAsync(output, 81920, token);
        }
    }

    static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }

    static Process StartProcess(string file, string arguments, string folder, out Task logs)
    {
        var info = new ProcessStartInfo
        {
            FileName = file, Arguments = arguments, WorkingDirectory = folder,
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        info.EnvironmentVariables["UV_PROJECT_ENVIRONMENT"] = Path.Combine(Home, "venv");
        info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
        info.EnvironmentVariables["PYTHONUTF8"] = "1";
        AppendLog(file + " " + arguments);
        Process process = Process.Start(info);
        if (process == null) throw new InvalidOperationException("음성 AI 실행을 시작하지 못했습니다.");
        logs = Task.WhenAll(LogOutput(process.StandardOutput), LogOutput(process.StandardError));
        return process;
    }

    static async Task RunStep(string file, string arguments, string folder, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        Task logs;
        using (var process = StartProcess(file, arguments, folder, out logs))
        {
            while (!process.HasExited) await Task.Delay(250, token);
            await logs;
            token.ThrowIfCancellationRequested();
            if (process.ExitCode != 0)
                throw new InvalidOperationException("음성 AI 설치 단계가 실패했습니다. 종료 코드: " + process.ExitCode);
        }
    }

    static async Task LogOutput(StreamReader reader)
    {
        try
        {
            string line;
            // 파일 기록만 하므로 Play가 끝나도 Unity 메인 스레드를 기다리지 않습니다.
            while ((line = await reader.ReadLineAsync().ConfigureAwait(false)) != null) AppendLog(line);
        }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }

    static void AppendLog(string message)
    {
        try { lock (LogLock) File.AppendAllText(LogPath, message + Environment.NewLine); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

#if !UNITY_EDITOR
    static void StopAI()
    {
        if (ownedProcess == null) return;
        try { if (!ownedProcess.HasExited) ownedProcess.Kill(); }
        catch (Exception error)
        {
            AppendLog(error.ToString());
            Debug.LogError("음성 AI를 종료하지 못했습니다.\n로그: " + LogPath);
        }
        finally
        {
            ownedProcess.Dispose();
            ownedProcess = null;
        }
    }
#endif

    void StartMicrophone()
    {
        if (!(startLevel >= 0f && startLevel <= 1f && silenceSeconds > 0f &&
              maxSeconds > 0f && preRollSeconds >= 0f && preRollSeconds < maxSeconds) ||
            float.IsInfinity(silenceSeconds + maxSeconds))
            throw new ArgumentException("RMS는 0~1, 무음·최대 시간은 양수, 사전 보관 시간은 최대 시간 미만이어야 합니다.");
        if (Microphone.devices.Length == 0)
            throw new InvalidOperationException("사용 가능한 마이크가 없습니다. 마이크 연결과 권한을 확인하세요.");

        int minRate, maxRate;
        Microphone.GetDeviceCaps(null, out minRate, out maxRate);
        int rate = minRate == 0 && maxRate == 0 ? 16000 : Math.Max(minRate, Math.Min(16000, maxRate));
        clip = Microphone.Start(null, true, 10, rate);
        if (clip == null)
            throw new InvalidOperationException("마이크 녹음을 시작하지 못했습니다. 마이크 권한을 확인하세요.");

        sampleRate = clip.frequency;
        chunk = new float[Math.Max(1, sampleRate / 20)];
        maxSamples = Math.Max(1, checked((int)((double)maxSeconds * sampleRate)));
        preRollSamples = (int)((double)preRollSeconds * sampleRate);
        readPosition = chunkCount = 0;
        nextLogTime = Time.realtimeSinceStartup + 0.5f;
    }

    void OnDisable()
    {
        StopAllCoroutines();
        if (lifetime != null)
        {
            lifetime.Cancel();
            lifetime.Dispose();
            lifetime = null;
        }
        Microphone.End(null);
        if (clip != null) Destroy(clip);
        clip = null;
        preRoll.Clear();
        recording.Clear();
        chunkCount = 0;
        SetState(State.Waiting);
    }

    IEnumerator Listen()
    {
        while (Microphone.GetPosition(null) <= 0)
            yield return null;

        while (isActiveAndEnabled)
        {
            int position = Microphone.GetPosition(null);
            if (position < 0)
            {
                Fail("마이크 위치를 읽지 못했습니다.");
                yield break;
            }
            // shortcut: 10초 이상 프레임이 멈추면 유실됩니다. 긴 정지가 필요하면 버퍼를 늘리세요.
            int frames = (position - readPosition + clip.samples) % clip.samples;
            if (frames > 0)
            {
                int channels = clip.channels;
                float[] samples = new float[frames * channels];
                if (!clip.GetData(samples, readPosition))
                {
                    Fail("마이크 오디오를 읽지 못했습니다.");
                    yield break;
                }
                readPosition = position;
                for (int i = 0; i < samples.Length && isActiveAndEnabled; i += channels)
                {
                    float mono = 0f;
                    for (int channel = 0; channel < channels; channel++)
                        mono += samples[i + channel];
                    chunk[chunkCount++] = mono / channels;
                    if (chunkCount == chunk.Length)
                    {
                        chunkCount = 0;
                        ProcessChunk();
                    }
                }
            }
            yield return null;
        }
    }

    void ProcessChunk()
    {
        double squares = 0;
        foreach (float sample in chunk) squares += sample * sample;
        float rms = (float)Math.Sqrt(squares / chunk.Length);
        if (logLevel && Time.realtimeSinceStartup >= nextLogTime)
        {
            Debug.Log("마이크 RMS: " + rms.ToString("F4"));
            nextLogTime = Time.realtimeSinceStartup + 0.5f;
        }
        if (CurrentState == State.Processing) return;

        bool loud = rms >= startLevel;
        if (CurrentState == State.Waiting)
        {
            if (!loud)
            {
                noiseLevel = noiseLevel < 0f ? rms : 0.95f * noiseLevel + 0.05f * rms;
                foreach (float sample in chunk) preRoll.Enqueue(sample);
                while (preRoll.Count > preRollSamples) preRoll.Dequeue();
                return;
            }
            recording.AddRange(preRoll);
            preRoll.Clear();
            SetState(State.Recording);
            if (!isActiveAndEnabled) return;
        }

        int count = Math.Min(chunk.Length, maxSamples - recording.Count);
        for (int i = 0; i < count; i++) recording.Add(chunk[i]);
        // 말하는 중에는 방 잡음의 2배만 넘어도 계속 말하는 것으로 봅니다: 작게 말한 "아 아니다"에서 끊기지 않게
        if (rms >= Math.Min(startLevel, Math.Max(2f * Math.Max(noiseLevel, 0f), 0.003f))) lastLoudSample = recording.Count;
        if (recording.Count < maxSamples &&
            recording.Count - lastLoudSample < silenceSeconds * sampleRate) return;

        byte[] wav = EncodeWav();
        recording.Clear();
        SetState(State.Processing);
        if (isActiveAndEnabled) Send(wav);
    }

    async void Send(byte[] wav)
    {
        CancellationToken token = lifetime.Token;
        VoiceResult result = null;
        string error = null, body = "", reason = "";
        int status = 0;
        try
        {
            using (var content = new ByteArrayContent(wav))
            {
                content.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
                using (var response = await Http.PostAsync(AiAddress + "/command", content, token))
                {
                    status = (int)response.StatusCode;
                    reason = response.ReasonPhrase;
                    body = await response.Content.ReadAsStringAsync();
                    token.ThrowIfCancellationRequested();
                    if (status != 200) throw new HttpRequestException("음성 명령 처리 실패");
                    result = JsonUtility.FromJson<VoiceResult>(body);
                    if (result == null || result.text == null || result.commands == null)
                        throw new FormatException("응답에 text 또는 commands가 없습니다.");
                    foreach (VoiceCommand command in result.commands)
                        if (command == null || string.IsNullOrEmpty(command.op))
                            throw new FormatException("응답에 유효하지 않은 명령이 있습니다.");
                }
            }
        }
        catch (Exception exception)
        {
            if (token.IsCancellationRequested) return;
            error = "HTTP " + status + " | " + reason + " | " + exception.Message + "\n" + body;
            AppendLog(error);
        }
        if (token.IsCancellationRequested) return;
        try
        {
            if (error != null) OnError?.Invoke("음성 명령을 처리하지 못했습니다.\n로그: " + LogPath);
            else OnCommands?.Invoke(result);
        }
        finally
        {
            if (!token.IsCancellationRequested && isActiveAndEnabled)
            {
                // 처리 중 들어온 소리와 미완성 청크가 다음 명령에 섞이지 않게 합니다.
                readPosition = Microphone.GetPosition(null);
                chunkCount = 0;
                SetState(State.Waiting);
            }
        }
    }

    byte[] EncodeWav()
    {
        int dataSize = checked(recording.Count * 2);
        byte[] wav = new byte[checked(44 + dataSize)];
        WriteTag(wav, 0, "RIFF");
        WriteInt(wav, 4, 36 + dataSize);
        WriteTag(wav, 8, "WAVE");
        WriteTag(wav, 12, "fmt ");
        WriteInt(wav, 16, 16);
        wav[20] = 1;
        wav[22] = 1;
        WriteInt(wav, 24, sampleRate);
        WriteInt(wav, 28, sampleRate * 2);
        wav[32] = 2;
        wav[34] = 16;
        WriteTag(wav, 36, "data");
        WriteInt(wav, 40, dataSize);
        for (int i = 0; i < recording.Count; i++)
        {
            int value = (int)Math.Round(Math.Max(-1f, Math.Min(1f, recording[i])) * 32767f);
            wav[44 + i * 2] = (byte)(value & 255);
            wav[45 + i * 2] = (byte)((value >> 8) & 255);
        }
        return wav;
    }

    static void WriteTag(byte[] bytes, int offset, string tag)
    {
        for (int i = 0; i < tag.Length; i++) bytes[offset + i] = (byte)tag[i];
    }

    static void WriteInt(byte[] bytes, int offset, int value)
    {
        for (int i = 0; i < 4; i++) bytes[offset + i] = (byte)((value >> (i * 8)) & 255);
    }

    void SetState(State state)
    {
        if (CurrentState == state) return;
        CurrentState = state;
        OnStateChanged?.Invoke(state);
    }

    void Fail(string message)
    {
        enabled = false;
        AppendLog(message);
        OnError?.Invoke(message + "\n로그: " + LogPath);
    }
}
