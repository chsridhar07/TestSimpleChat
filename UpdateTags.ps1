#Script to ADD tags
# -----------------------------
# Add/Update tag on a RG + all resources within it (merge tags)
# -----------------------------

param(
    [Parameter(Mandatory = $true)]
    [string] $ResourceGroupName,
    [string] $sub,

    [hashtable] $Tags,
    [string[]] $TagPairs,

    [string] $TagName = "",
    [string] $TagValue = "",

    [switch] $WhatIf
)

# Ensure you're authenticated and a subscription is selected
# Connect-AzAccount
# Set-AzContext -Subscription "<subscriptionIdOrName>"

#Connect-AzAccount
Connect-AzAccount -Environment AzureUSGovernment
Write-Host("Connected to Azure");

Set-AzContext -Subscription $sub

$tagHash = @{}

if ($Tags) {
    foreach ($key in $Tags.Keys) {
        $tagHash[$key] = [string]$Tags[$key]
    }
}

if ($TagPairs) {
    foreach ($pair in $TagPairs) {
        if ($pair -notmatch '=') {
            throw "Invalid tag pair '$pair'. Use the format 'TagName=TagValue'."
        }

        $name, $value = $pair -split '=', 2
        $name = $name.Trim()
        $value = $value.Trim()

        if ([string]::IsNullOrWhiteSpace($name)) {
            throw "Invalid tag pair '$pair'. Tag name cannot be empty."
        }

        $tagHash[$name] = $value
    }
}

# Backward compatibility for existing callers using TagName/TagValue only.
if ($tagHash.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace($TagName)) {
    $tagHash[$TagName] = $TagValue
}

if ($tagHash.Count -eq 0) {
    throw "No tags provided. Use -Tags @{Key='Value'} or -TagPairs 'Key=Value'."
}

$tagSummary = ($tagHash.GetEnumerator() | ForEach-Object { "{0}='{1}'" -f $_.Key, $_.Value }) -join ', '

Write-Host "Tagging Resource Group '$ResourceGroupName' with tags: $tagSummary ..." -ForegroundColor Cyan

# 1) Tag the Resource Group
$rg = Get-AzResourceGroup -Name $ResourceGroupName -ErrorAction Stop

if ($WhatIf) {
    Write-Host "[WhatIf] Would merge tag into Resource Group: $($rg.ResourceId)"
}
else {
    Update-AzTag -ResourceId $rg.ResourceId -Tag $tagHash -Operation Merge -ErrorAction Stop | Out-Null
}

# 2) Tag all resources in the Resource Group
Write-Host "Enumerating resources in Resource Group '$ResourceGroupName' ..." -ForegroundColor Cyan
$resources = Get-AzResource -ResourceGroupName $ResourceGroupName -ErrorAction Stop

Write-Host ("Found {0} resources. Tagging..." -f $resources.Count) -ForegroundColor Yellow

$failed = New-Object System.Collections.Generic.List[object]

foreach ($res in $resources) {
    try {
        if ($WhatIf) {
            Write-Host "[WhatIf] Would merge tag into Resource: $($res.ResourceId)"
        }
        else {
            Update-AzTag -ResourceId $res.ResourceId -Tag $tagHash -Operation Merge -ErrorAction Stop | Out-Null
        }
    }
    catch {
        $failed.Add([pscustomobject]@{
                ResourceName = $res.Name
                ResourceType = $res.ResourceType
                ResourceId   = $res.ResourceId
                Error        = $_.Exception.Message
            })
        Write-Warning "Failed to tag: $($res.ResourceId) - $($_.Exception.Message)"
    }
}

Write-Host "Done." -ForegroundColor Green

if ($failed.Count -gt 0) {
    Write-Host "`nSome resources failed to tag:" -ForegroundColor Red
    $failed | Format-Table -AutoSize
    Write-Host "`nTip: Some resources (or child resources) may not support tags, or may require tagging the parent instead." -ForegroundColor DarkYellow
}