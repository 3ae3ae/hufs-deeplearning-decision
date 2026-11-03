using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;

public class RobotVoiceBuildProcessor : IPostprocessBuildWithReport
{
    public int callbackOrder { get { return 0; } }

    public void OnPostprocessBuild(BuildReport report)
    {
        BuildTarget target = report.summary.platform;
        if (target != BuildTarget.StandaloneWindows && target != BuildTarget.StandaloneWindows64 &&
            target != BuildTarget.StandaloneOSX) return;
        var package = UnityEditor.PackageManager.PackageInfo.FindForAssembly(typeof(VoiceCommands).Assembly);
        if (package == null || !Directory.Exists(Path.Combine(package.resolvedPath, "AI~")))
            throw new BuildFailedException("음성 AI 파일이 없습니다. 생성한 tarball로 패키지를 설치하십시오.");

        string output = report.summary.outputPath;
        string assets = target == BuildTarget.StandaloneOSX
            ? Path.Combine(output, "Contents", "Resources", "Data", "StreamingAssets")
            : Path.Combine(Path.GetDirectoryName(output), Path.GetFileNameWithoutExtension(output) + "_Data", "StreamingAssets");
        string destination = Path.Combine(assets, "RobotVoiceAI");
        if (Directory.Exists(destination)) Directory.Delete(destination, true);
        CopyFolder(Path.Combine(package.resolvedPath, "AI~"), destination);
    }

    static void CopyFolder(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (string file in Directory.GetFiles(source))
            File.Copy(file, Path.Combine(destination, Path.GetFileName(file)), true);
        foreach (string folder in Directory.GetDirectories(source))
            CopyFolder(folder, Path.Combine(destination, Path.GetFileName(folder)));
    }
}
