const express = require("express");
const ytdlp = require("yt-dlp-exec");

const app = express();

app.get("/api", async (req, res) => {

const url = req.query.url;

if (!url) {
return res.json({ error: "No URL provided" });
}

try {

const info = await ytdlp(url, {
dumpSingleJson: true
});

const video = info.url;

// best audio format
const audioFormat = info.formats
.filter(f => f.vcodec === "none" && f.acodec !== "none")
.sort((a,b) => (b.abr || 0) - (a.abr || 0))[0];

const audio = audioFormat ? audioFormat.url : null;

res.json({
title: info.title,
thumbnail: info.thumbnail,
video,
audio
});

} catch (err) {

console.log(err);

res.json({
error: "Download failed"
});

}

});

app.listen(3000, () => {
console.log("Downloader running on port 3000");
});