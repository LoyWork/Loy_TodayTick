param(
    [Parameter(Mandatory)][string]$Executable,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$')][string]$Version,
    [Parameter(Mandatory)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $Executable).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $output -Force | Out-Null
$stem = "TodayTick-v$Version-windows-x64"
$exe = Join-Path $output "$stem.exe"
$zip = Join-Path $output "$stem.zip"
if ($source -eq $exe) { throw '输出目录不能覆盖输入程序' }
Copy-Item -LiteralPath $source -Destination $exe -Force
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }

# Only the executable enters the archive; reminders and WebView profiles stay local.
$archive = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Create)
try {
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $archive, $exe, 'TodayTick.exe', [IO.Compression.CompressionLevel]::Optimal
    ) | Out-Null
} finally {
    $archive.Dispose()
}
$checksums = foreach ($file in @($exe, $zip)) {
    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($file))"
}
$checksums | Set-Content -LiteralPath (Join-Path $output 'SHA256SUMS.txt') -Encoding ascii
Get-ChildItem -LiteralPath $output -File | Select-Object Name, Length
