# ==============================================================================
# ⚡ Antigravity Token Tracker — Script d'Installation Universel
# Lie automatiquement le plugin, la skill et l'extension IDE dans Antigravity.
# ==============================================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "`n⚡ Installation d'Antigravity Token Tracker..." -ForegroundColor Cyan

$RepoDir = $PSScriptRoot
$GeminiPluginsDir = Join-Path $HOME ".gemini\config\plugins"
$GeminiSkillsDir = Join-Path $HOME ".gemini\config\skills"
$IdeExtensionsDir = Join-Path $HOME ".antigravity-ide\extensions"

# 1. Plugin junction dans Antigravity
if (-not (Test-Path $GeminiPluginsDir)) {
    New-Item -ItemType Directory -Path $GeminiPluginsDir -Force | Out-Null
}
$PluginTarget = Join-Path $GeminiPluginsDir "antigravity-token-tracker"
if (Test-Path $PluginTarget) {
    Remove-Item $PluginTarget -Force -Recurse -ErrorAction SilentlyContinue
}
New-Item -ItemType Junction -Path $PluginTarget -Target $RepoDir | Out-Null
Write-Host "✅ [1/3] Plugin lié dans : $PluginTarget" -ForegroundColor Green

# 2. Skill globale dans Antigravity
if (-not (Test-Path $GeminiSkillsDir)) {
    New-Item -ItemType Directory -Path $GeminiSkillsDir -Force | Out-Null
}
$SkillTarget = Join-Path $GeminiSkillsDir "token-tracker"
$SkillSource = Join-Path $RepoDir "skills\token-tracker"
if (Test-Path $SkillTarget) {
    Remove-Item $SkillTarget -Force -Recurse -ErrorAction SilentlyContinue
}
New-Item -ItemType Junction -Path $SkillTarget -Target $SkillSource | Out-Null
Write-Host "✅ [2/3] Skill globale liée dans : $SkillTarget" -ForegroundColor Green

# 3. Extension Antigravity IDE (Bouton dans la barre d'état)
$ParentIde = Split-Path $IdeExtensionsDir
if (Test-Path $ParentIde) {
    if (-not (Test-Path $IdeExtensionsDir)) {
        New-Item -ItemType Directory -Path $IdeExtensionsDir -Force | Out-Null
    }
    $ExtTarget = Join-Path $IdeExtensionsDir "antigravity-token-tracker"
    $ExtSource = Join-Path $RepoDir "ide-extension"
    if (Test-Path $ExtTarget) {
        Remove-Item $ExtTarget -Force -Recurse -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Junction -Path $ExtTarget -Target $ExtSource | Out-Null
    Write-Host "✅ [3/3] Extension IDE liée dans : $ExtTarget" -ForegroundColor Green
} else {
    Write-Host "ℹ️ [3/3] Dossier Antigravity IDE non détecté (optionnel)." -ForegroundColor DarkGray
}

# 4. Initialisation des métriques locales
Write-Host "`n📊 Initialisation du tableau de bord..." -ForegroundColor Yellow
try {
    python "$RepoDir\scripts\tracker.py" --html | Out-Null
    Write-Host "✅ Tableau de bord initialisé avec vos données locales !" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Python non trouvé ou erreur lors du premier calcul." -ForegroundColor Yellow
}

Write-Host "`n🎉 INSTALLATION TERMINÉE AVEC SUCCÈS !" -ForegroundColor Cyan
Write-Host "👉 Ouvrez votre Antigravity ou tapez /tokens dans le chat pour voir vos métriques." -ForegroundColor White
Write-Host "👉 Double-cliquez sur open_dashboard.bat à tout moment pour ouvrir le dashboard.`n" -ForegroundColor White
