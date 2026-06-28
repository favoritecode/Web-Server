$urls = @(
    "https://host.favoriteweb.net/offline/index.m3u8",
    "https://host.favoriteweb.net/live/live/index.m3u8",
    "https://khan.favoriteweb.net/offline/index.m3u8",
    "https://khan.favoriteweb.net/live/live/index.m3u8",
    "https://server.favoriteweb.net/__offline/offline.ts?seq=test",
    "https://server.favoriteweb.net/live.m3u8"
)

foreach ($url in $urls) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing $url -MaximumRedirection 5 -TimeoutSec 20
        $content = $response.Content
        if ($content -is [byte[]]) {
            $content = [Text.Encoding]::UTF8.GetString($content)
        }

        [pscustomobject]@{
            Url = $url
            Status = $response.StatusCode
            StartsM3U = $content.StartsWith("#EXTM3U")
            HasStream = ($content -match "STREAM-INF|EXTINF")
            FinalUrl = $response.BaseResponse.ResponseUri.AbsoluteUri
        }
    } catch {
        [pscustomobject]@{
            Url = $url
            Status = "ERR"
            StartsM3U = $false
            HasStream = $false
            FinalUrl = $_.Exception.Message
        }
    }
}
