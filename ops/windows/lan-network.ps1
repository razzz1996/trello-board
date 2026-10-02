function Get-ProductivityLanBinding {
    [CmdletBinding()]
    param([string]$PreferredAlias = "Ethernet")

    $addresses = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction Stop |
        Where-Object {
            $_.IPAddress -ne "127.0.0.1" -and
            $_.IPAddress -notlike "169.254.*" -and
            -not $_.SkipAsSource
        }

    $selected = $addresses |
        Where-Object { $_.InterfaceAlias -eq $PreferredAlias } |
        Select-Object -First 1

    if (-not $selected) {
        $selected = $addresses |
            Where-Object {
                $_.InterfaceAlias -notmatch "Nord|OpenVPN|Loopback|vEthernet|Bluetooth"
            } |
            Select-Object -First 1
    }

    if (-not $selected) {
        throw "No usable private IPv4 LAN address was found."
    }
    $hostAddress = [System.Net.IPAddress]::Parse($selected.IPAddress)
    $bytes = $hostAddress.GetAddressBytes()
    $networkBytes = New-Object byte[] 4
    $remaining = [int]$selected.PrefixLength

    for ($index = 0; $index -lt 4; $index++) {
        $bits = [Math]::Min([Math]::Max($remaining, 0), 8)
        $mask = if ($bits -eq 0) { 0 } else { 256 - [Math]::Pow(2, 8 - $bits) }
        $networkBytes[$index] = $bytes[$index] -band [int]$mask
        $remaining -= 8
    }

    $network = ([System.Net.IPAddress]::new($networkBytes)).ToString()
    [pscustomobject]@{
        Host = $selected.IPAddress
        PrefixLength = [int]$selected.PrefixLength
        NetworkCidr = "$network/$($selected.PrefixLength)"
        InterfaceAlias = $selected.InterfaceAlias
    }
}
