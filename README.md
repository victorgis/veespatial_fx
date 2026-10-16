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

A signal is an intraday ICWR setup on the last **closed 5-minute** candle.

- The active wave is the nearest completed swing of at least 40 pips. A smaller swing closer to now is ignored. When a newer swing reaches 40 pips, it replaces the active wave and the old Fibonacci levels are dropped.
- Fibonacci levels are drawn from the wave low (0) to the wave high (1). The band from 0.382 to 0.618 is the retracement channel. 0.250 and 0.750 are the confirmation levels.
- The channel has to be entered first: some later candle closes inside it. The signal is the next whole candle beyond a confirmation level. Wholly above 0.750 is a buy. Wholly below 0.250 is a sell. A wick that still touches the level does not count.
- A new trade also needs the daily 14-period RSI on the same side of 50. Above 50 confirms a buy. Below 50 confirms a sell. RSI at 50 confirms nothing.
- The stop is 50 pips from the entry. There is no fixed target. An open trade closes when the opposite ICWR signal prints (the daily RSI is not required for that exit) or when the 50-pip stop is hit.

One signal per market at a time. The opposite signal closes the open trade, and if the daily RSI agrees with the new direction the desk reverses on that same candle. A trade does not expire on a timer.

Forex uses the pair's own pip, so 40 pips on USDJPY is 0.40. Gold, oil, indices, and the other non-forex markets have no pip in these rules. On those markets one pip is 0.01% of price, so 40 pips is 0.40% of price and the stop is 0.50% of price.

Every signal is posted to Telegram as soon as it appears. Automatic accounts do not take all of them. Three open automatic trades is the usual limit, and five is the most. Anything past that stays on Telegram and on the desk for a manual entry. The service log prints one line per market on every scan, with the active wave, the daily RSI, and why a trade was or was not taken.

Prices come from Yahoo Finance. A forex order is skipped if the broker price has already run more than 40% of the way to the stop. Gold, silver, WTI, Brent, natural gas, copper, and soybeans are filled at the MT5 price. The stop keeps the signal's distance, and that distance is rescaled when the broker quotes a different unit, such as soybeans in dollars instead of cents. The copier places the stop and no take profit, then closes the position when the opposite signal prints. Download SignalBridge again so an older copier, which still attached a target, is replaced.

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
