from __future__ import annotations

AUDIO_FILTERS: dict[str, str] = {
    "none":       "",
    "bassboost":  "equalizer=f=100:width_type=o:width=2:g=10",
    "nightcore":  "asetrate=44100*1.25,aresample=44100,atempo=1.06",
    "vaporwave":  "asetrate=44100*0.8,aresample=44100,atempo=0.9",
    "echo":       "aecho=0.8:0.9:1000:0.3",
    "8d":         "apulsator=hz=0.08",
}
