#Script to ADD tags
# -----------------------------
# Add/Update tag on a RG + all resources within it (merge tags)
# -----------------------------

param(
	[Parameter(Mandatory = $true)]
	[string] $ResourceGroupName,
    [string] $sub,

	[string] $TagName  = "Business Group",
	[string] $TagValue = "ITD EAS",

	[switch] $WhatIf
)

# Ensure you're authenticated and a subscription is selected
# Connect-AzAccount
# Set-AzContext -Subscription "<subscriptionIdOrName>"

#Connect-AzAccount
Connect-AzAccount -Environment AzureUSGovernment
Write-Host("Connected to Azure");

Set-AzContext -Subscription $sub

$tagHash = @{ $TagName = $TagValue }

Write-Host "Tagging Resource Group '$ResourceGroupName' with $TagName='$TagValue' ..." -ForegroundColor Cyan

# 1) Tag the Resource Group
$rg = Get-AzResourceGroup -Name $ResourceGroupName -ErrorAction Stop

if ($WhatIf) {
	Write-Host "[WhatIf] Would merge tag into Resource Group: $($rg.ResourceId)"
} else {
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
    	} else {
        	Update-AzTag -ResourceId $res.ResourceId -Tag $tagHash -Operation Merge -ErrorAction Stop | Out-Null
    	}
	}
	catch {
    	$failed.Add([pscustomobject]@{
        	ResourceName = $res.Name
        	ResourceType = $res.ResourceType
        	ResourceId   = $res.ResourceId
        	Error    	= $_.Exception.Message
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
