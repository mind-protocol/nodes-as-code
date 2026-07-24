param(
    [string]$Graph = "mind_kernel_v0",
    [string]$Repo = (Get-Location).Path
)

Write-Warning "Cette commande historique lance maintenant le daemon graphé. L'intervalle est lu depuis schedule_policy.interval_seconds."
python -m mind_node_runtime daemon --graph $Graph --repo $Repo
