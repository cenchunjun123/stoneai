# sync_skills.ps1 -- sync my-* skills from the common source to every endpoint
# Source : ~/.agents/skills/my-*        (authoritative, edit ONLY here)
# Targets: .claude/.dsh/.codex/.zcode/.agents skills dirs (mirrors, read-only)
# Rules  : sync my-* self-maintained skills only; never touch third-party
#          skills on each endpoint; always skip __pycache__
$ErrorActionPreference = "Stop"
$home2 = $env:USERPROFILE
$src = Join-Path $home2 ".agents\skills"
$targets = @(".claude\skills", ".dsh\skills", ".codex\skills", ".zcode\skills", ".agents\skills")

if (-not (Test-Path $src)) { Write-Host "source not found: $src"; exit 1 }

$skills = Get-ChildItem $src -Directory | Where-Object { $_.Name -like "my-*" }
Write-Host "my-* skills in source: $($skills.Count)"
$skills | ForEach-Object { Write-Host "  - $($_.Name)" }
Write-Host ""

$copied = 0; $skipped = 0
foreach ($t in $targets) {
    $root = Join-Path $home2 $t
    if (-not (Test-Path $root)) { continue }
    $tag = $t.Split('\')[0]
    foreach ($s in $skills) {
        $dst = Join-Path $root $s.Name
        $srcMain = Join-Path $s.FullName "SKILL.md"
        $dstMain = Join-Path $dst "SKILL.md"
        if ((Test-Path $dstMain) -and (Test-Path $srcMain)) {
            $h1 = (Get-FileHash $srcMain -Algorithm SHA256).Hash
            $h2 = (Get-FileHash $dstMain -Algorithm SHA256).Hash
            if ($h1 -eq $h2) { $skipped++; continue }
        }
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item $s.FullName $dst -Recurse
        Get-ChildItem $dst -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        $copied++
        Write-Host "  [$tag] <- $($s.Name)"
    }
}
Write-Host ""
Write-Host "updated: $copied, already current: $skipped"
