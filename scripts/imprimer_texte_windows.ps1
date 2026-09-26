param(
    [Parameter(Mandatory = $true)]
    [string]$Fichier,
    [Parameter(Mandatory = $true)]
    [string]$Imprimante
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not (Test-Path -LiteralPath $Fichier -PathType Leaf)) {
    throw "Fichier introuvable : $Fichier"
}

$document = New-Object System.Drawing.Printing.PrintDocument
$document.PrinterSettings.PrinterName = $Imprimante
if (-not $document.PrinterSettings.IsValid) {
    throw "Imprimante Windows invalide : $Imprimante"
}

$texte = [System.IO.File]::ReadAllText($Fichier)
$lignes = $texte -split "`r?`n"
$index = 0
$police = New-Object System.Drawing.Font("Consolas", 9)
$hauteur = $police.GetHeight()

$document.add_PrintPage({
    param($sender, $event)
    $y = [single]$event.MarginBounds.Top
    while ($script:index -lt $script:lignes.Count) {
        if (($y + $script:hauteur) -gt $event.MarginBounds.Bottom) {
            $event.HasMorePages = $true
            return
        }
        $event.Graphics.DrawString(
            $script:lignes[$script:index],
            $script:police,
            [System.Drawing.Brushes]::Black,
            [single]$event.MarginBounds.Left,
            $y
        )
        $script:index++
        $y += $script:hauteur
    }
    $event.HasMorePages = $false
})

try {
    $document.Print()
}
finally {
    $police.Dispose()
    $document.Dispose()
}
