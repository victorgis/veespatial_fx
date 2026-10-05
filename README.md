# Signal Desk

A small desk for XM signals. It watches major currency pairs, gold, WTI cash (`OILCash`), and Brent cash (`BRENTCash`). One signal goes to your Telegram channel and to every account on the site. Each person chooses what happens next.

- **Automatic.** A copier inside MT4 or MT5 places the order on that person’s XM account.
- **Signals only.** They place it themselves on MT4, MT5, or the XM app, using the prices and the lot size on the signal.

XM does not offer an order API the website can call, and Railway or Render cannot run the MetaTrader terminal. The site decides the signal and the size. The copier, running where the account is logged in, sends the order.

## Account size

| | Standard | Micro |
| --- | --- | --- |
| Forex, 1 lot | 100,000 | 1,000 |
| About 1 pip on 1 lot of EURUSD | $10 | $0.10 |
| Gold, 1 lot on XM | 100 ounces | 1 ounce |
| OILCash and BRENTCash, 1 lot | 100 barrels | 100 barrels |

Forex and gold use a lot number 100 times larger on a micro account for the same position. Cash oil does not. XM lists those as 100 barrels per lot on either account. The copier reads the contract size from the terminal and will pause automatic orders when a forex contract does not match the account type you picked.

Size is a percent of balance, capped by the maximum lots you set, and never rounded up to a minimum that would risk more than that percent.

## What a signal is

A signal is a pullback on the last **closed 5-minute** candle, inside the higher-timeframe trend.

- The 1-hour trend has to agree. Price and the 50-hour average are on the same side of the 200-hour average. A flat hour produces no trade.
- The 15-minute swings have to agree: higher highs and higher lows for a buy, lower highs and lower lows for a sell. A mixed swing is allowed only when the latest swing still holds in the trade’s direction.
- On the 5-minute candle, RSI is in a pullback band and turning (about 40–58 and rising for a buy), MACD momentum is turning with the trend, and price has closed back through the 50-bar average without being extended past it. A fresh 1-minute candle has to close the same way.
- The stop sits beyond that recent swing, and only when the distance is about 0.8 to 2 times the 5-minute range. The target is 1.8 times the stop.

One signal per market at a time. After it closes, the next one on that market waits 15 minutes. An idea that has not hit the stop or the target expires after 6 hours.

Every signal is posted to Telegram as soon as it appears. Automatic accounts do not take all of them. Three open automatic trades is the usual limit, and five is the most. Anything past that stays on Telegram and on the desk for a manual entry. The service log prints one line per market on every scan, with the 1-hour trend, RSI, MA50, EMA200, MACD, and the 15-minute structure, whether or not a trade is taken.

Prices come from Yahoo Finance real-time market data. WTI and Brent are cash CFDs matching XM’s OILCash and BRENTCash quotes. The copier skips an order if the broker price has already moved more than a quarter of the way to the stop.

This is a rules alert. It is not a promise of profit, and it is not a measured win rate. A stop can be skipped in a fast market.

## Run it locally

Use Python 3.12 (3.14 does not yet have wheels for the data libraries).

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The first account becomes the admin and can press “Scan now”.

```bash
cd backend && .venv/bin/pytest
```

## Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token. If a token is ever pasted into a log or a chat, revoke it in BotFather and put the new one in the host’s environment.
2. Add the bot to your channel as an admin, with permission to post.
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`. A channel id looks like `-100…`. Forward a channel post to [@getidsbot](https://t.me/getidsbot) to read it. A public channel can use its `@name` once the bot is an admin. `chat not found` means the id is wrong or the bot is not in that channel.

The channel shows both the standard and the micro lot for a $1,000 account at 1% risk. Each person’s own size is on their dashboard.

## Connect MT4 or MT5

1. On the site, choose Automatic and the account type.
2. Copy the copier key. It is shown once.
3. Download `SignalBridge.mq5` or `SignalBridge.mq4` from the Guide page (the files also live in `experts/`).
4. Copy the file into `MQL5/Experts` or `MQL4/Experts`, then compile it.
5. In Tools → Options → Expert Advisors, allow algorithmic trading and allow WebRequest for your site’s origin, with no path.
6. Attach SignalBridge to any chart. Set `ApiBase` to that origin and paste the key. Turn on AutoTrading.

Leave the terminal running. A small VPS is the usual way to keep it online overnight. `OILCash` and `BRENTCash` are MT5 markets at XM.

If your platform uses a different symbol name, add a line in Settings → Advanced, for example `oil=OILCash.pro`.

## Deploy on Railway or Render

Both hosts build the `Dockerfile`. The image serves the API and the website on one port (`$PORT`).

Set:

- `ENV=production`
- `JWT_SECRET` to a long random string
- `DATABASE_URL` to a Postgres URL (required — the disk is wiped on redeploy, so SQLite would lose accounts). Neon’s pooled URL works. Keep `sslmode=require` and `channel_binding=require` on the end. Put it in the host’s environment, not in the repository.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`
- `CRON_KEY` if you want an external scheduler

`render.yaml` and `railway.toml` are included. On Render’s free instance the process sleeps, and the in-process timer sleeps with it. Point a cron service at:

```bash
curl -X POST -H "X-Cron-Key: $CRON_KEY" https://YOUR-APP/api/system/scan
```

every minute, so a closed 5-minute candle is posted quickly. An always-on instance can rely on `SCHEDULER_ENABLED=true` alone. The log line for each market is the check itself: you do not have to wait for Telegram to see that RSI, MACD, MA50, and EMA200 were read.

Health check: `GET /api/health`.

## Reset a password

```bash
cd backend && python -m app.cli reset-password ada@example.com 'a-new-password'
```
