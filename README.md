# gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/joshwilsonwill-boop/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/joshwilsonwill-boop/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

GTA 6 Twitch CCU Forecast - hour-by-hour quantile forecast of Grand Theft Auto VI's launch-day Twitch viewers from the first hour's print. It reads a case file (the first hour's viewer count plus every comparable past launch's hourly curve) and writes five quantiles (5%, 25%, 50%, 75%, 95%) for each of hours 2 to 24 of the release day.

## How it forecasts

Each comparable launch is reduced to its launch-day shape: the log of each hour's viewers over that launch's hour-1 viewers. The forecast median for an hour is the weighted median of those log shapes, with a comparable's weight from a Gaussian kernel on how close its own hour-1 size is to this case's hour-1 print (launches that opened at a similar scale grew the most like this one), restricted to console-only launches when enough of them carry weight. The kernel widens automatically until the effective sample is at least six launches, so a huge opening never rests on one or two comparables. The spread for an hour comes from the weighted interquartile range of the same log shapes. A small share of the median comes from a ridge fit of the log shape on log hour-1 distance and a console flag, which pulls small openings up and big openings down along the slope the comparables show.

On the four practice launches (Marvel's Wolverine, Red Dead Redemption 2, God of War Ragnarok, Marvel's Spider-Man 2) it scores a mean pinball loss of 0.201, against the house baseline's 0.387.

## What it forecasts

The charts below are real output from the practice launches: the program's forecasts against the actual Twitch viewer counts, plus its pinball loss against the house baseline.

![God of War Ragnarok: forecast vs actual Twitch viewers, hours 1 to 24](screenshots/1-ragnarok.png)

God of War Ragnarok, the best practice case: pinball loss 0.161, and the actual count stayed inside the 5-95% interval in all 23 forecast hours.

![Marvel's Wolverine: forecast vs actual Twitch viewers, hours 1 to 24](screenshots/2-wolverine.png)

Marvel's Wolverine, the hardest practice case: pinball loss 0.298. The evening surge (actual peak 212,243 viewers at hour 21) ran above the forecast median, which is why this case scores worst.

![Pinball loss on the four practice launches, this forecast vs the house baseline](screenshots/3-losses.png)

Across all four practice launches the mean pinball loss is 0.201 against the house baseline's 0.387.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` case in the input directory and writes one `*.out` forecast per case. Python 3.13, standard library only, no network, deterministic: two runs on the same case write the same bytes.

---

<sub>Entered on [make.fun](https://make.fun/?ref=mc9159gw&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
