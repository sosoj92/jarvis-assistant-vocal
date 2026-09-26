param(
    [Parameter(Mandatory = $true)]
    [string]$DossierImages,
    [Parameter(Mandatory = $true)]
    [string]$Imprimante,
    [switch]$RectoVerso
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$document = New-Object System.Drawing.Printing.PrintDocument
$document.PrinterSettings.PrinterName = $Imprimante
if (-not $document.PrinterSettings.IsValid) {
    throw "Imprimante Windows invalide : $Imprimante"
}
if ($RectoVerso) {
    if (-not $document.PrinterSettings.CanDuplex) {
        throw "L'imprimante ne signale pas de prise en charge du recto verso : $Imprimante"
    }
    # Portrait + retournement sur le bord vertical = reliure sur le bord long.
    $document.PrinterSettings.Duplex = [System.Drawing.Printing.Duplex]::Vertical
}
$document.OriginAtMargins = $false
$document.DefaultPageSettings.Landscape = $false
$document.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(0, 0, 0, 0)
$a4 = $document.PrinterSettings.PaperSizes | Where-Object {
    $_.Kind -eq [System.Drawing.Printing.PaperKind]::A4
} | Select-Object -First 1
if ($null -ne $a4) {
    $document.DefaultPageSettings.PaperSize = $a4
}
$script:pages = @(Get-ChildItem -LiteralPath $DossierImages -Filter "page-*.png" -File | Sort-Object {
    $numero = [regex]::Match($_.BaseName, '\d+$').Value
    if ($numero) { [int]$numero } else { [int]::MaxValue }
})
if ($script:pages.Count -eq 0) {
    throw "Aucune page PNG a imprimer dans : $DossierImages"
}
$script:indexPage = 0

$document.add_PrintPage({
    param($sender, $event)
    # Le PDF contient deja ses marges editoriales. MarginBounds ajoutait encore
    # les marges Windows (souvent 25,4 mm), ce qui miniaturisait toute la page.
    # PageBounds envoie donc l'A4 a sa taille reelle ; le pilote ne rogne que sa
    # zone physiquement non imprimable, situee dans le blanc du gabarit.
    $bounds = $event.PageBounds
    $event.Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $event.Graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $bitmap = [System.Drawing.Image]::FromFile($script:pages[$script:indexPage].FullName)
    try {
        $event.Graphics.DrawImage($bitmap, $bounds)
    }
    finally {
        $bitmap.Dispose()
    }
    $script:indexPage += 1
    $event.HasMorePages = $script:indexPage -lt $script:pages.Count
})

try {
    $document.Print()
}
finally {
    $document.Dispose()
}
