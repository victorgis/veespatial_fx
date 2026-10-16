import { useState } from "react";
import { desk } from "../api";
import { useAuth } from "../auth";
import { when } from "../format";

export function Guide() {
  const { me, refresh } = useAuth();
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!me) return null;
  const origin = window.location.origin;

  return (
    <>
      <header className="page-head">
        <h1>How a trade gets placed</h1>
        <p className="lede">
          XM accepts the order inside MT4, MT5, or its own app. This website decides the signal and the size. The copier
          on your platform sends the order when you have chosen automatic.
        </p>
      </header>
      <div className="stack">
        <article className="card">
          <h2>Connection</h2>
          <p>
            {me.connection.online
              ? `Connected${me.connection.broker ? ` to ${me.connection.broker}` : ""}${me.connection.account_login ? ` · ${me.connection.account_login}` : ""}.`
              : `Not connected. Last seen ${when(me.connection.last_seen)}.`}
          </p>
          {me.connection.fx_contract ? (
            <p className="help">
              {me.connection.fx_symbol} contract size {me.connection.fx_contract.toLocaleString()}.{" "}
              {me.connection.detected_account_type === "standard"
                ? "That is a standard account (1 lot = 100,000)."
                : me.connection.detected_account_type === "micro"
                  ? "That is a micro account (1 lot = 1,000)."
                  : "That size is unusual. Check the symbol specification."}
            </p>
          ) : (
            <p className="help">When the copier connects, the contract size reported here is the check for standard versus micro.</p>
          )}
          <p className="help">Key on file: {me.settings.ea_key_prefix ? `${me.settings.ea_key_prefix}…` : "none yet"}.</p>
          {key ? <p className="keybox">{key}</p> : null}
          {error ? <p className="error">{error}</p> : null}
          <div className="actions">
            <button
              className="btn ghost"
              type="button"
              disabled={busy}
              onClick={async () => {
                if (!window.confirm("Create a new key? The copier will stop until you paste it.")) return;
                setBusy(true);
                try {
                  const next = await desk.rotateKey();
                  setKey(next.ea_key);
                  await refresh();
                } catch (err) {
                  setError(err instanceof Error ? err.message : "Could not create a key.");
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Creating…" : "Create a new copier key"}
            </button>
          </div>
        </article>
        <article className="card">
          <h2>Attach the copier</h2>
          <ol className="guide">
            <li>Choose Automatic in Settings, and MT5 if you want OILCash or BRENTCash.</li>
            <li>Download <a href="/api/downloads/SignalBridge.mq5">SignalBridge.mq5</a> or <a href="/api/downloads/SignalBridge.mq4">SignalBridge.mq4</a>.</li>
            <li>In MetaTrader, File → Open Data Folder → MQL5 (or MQL4) → Experts. Copy the file in and refresh the Navigator.</li>
            <li>Tools → Options → Expert Advisors. Allow algorithmic trading. Allow WebRequest for <span className="keybox" style={{ display: "inline" }}>{origin}</span>.</li>
            <li>Drag SignalBridge onto any chart. Set ApiBase to that same address and paste the copier key. Turn on AutoTrading.</li>
            <li>This page should say connected within a few seconds. Leave the terminal running. A small VPS is the usual way to keep it online overnight.</li>
          </ol>
        </article>
        <article className="card">
          <h2>Place a signal by hand</h2>
          <ol className="guide">
            <li>Read the entry, the 50-pip stop, and the lot size for your account type. Copy levels puts them on the clipboard. There is no take profit.</li>
            <li>On a standard account, 1 forex lot is 100,000. On a micro account it is 1,000, so the lot number is 100 times larger for the same position.</li>
            <li>For gold, XM uses the same 100× relationship (100 ounces versus 1 ounce). For OILCash and BRENTCash, 1 lot is 100 barrels on both.</li>
            <li>If the card says the minimum lot would risk more than your limit, skip the trade.</li>
          </ol>
        </article>
        <article className="card">
          <h2>How a signal is chosen</h2>
          <p>
            A signal follows the intraday ICWR rules on the 5-minute chart. The active wave is the nearest
            completed swing of at least 40 pips. Fibonacci levels run from that wave’s low to its high. After a
            candle closes inside the 38.2–61.8 retracement channel, a whole candle beyond the 75% level is a buy
            and a whole candle beyond the 25% level is a sell. A wick that still touches the level is not a signal.
            The daily 14-period RSI has to be above 50 for a buy and below 50 for a sell. The stop is 50 pips.
            There is no take profit. The trade closes when the opposite ICWR signal prints, or when the stop is hit.
          </p>
          <p>
            Every signal is posted to Telegram as soon as the candle closes. An automatic account does not take all
            of them: three open automatic trades is the usual limit, and five is the most. The rest stay on the
            channel and on this desk for you to place by hand. An automatic account also closes the position when
            the opposite signal prints, so use the current SignalBridge file.
          </p>
          <p className="help">
            Prices come from Yahoo Finance. A forex order is skipped if the broker price has already run
            more than 40% of the way to the stop. Gold, silver, WTI, Brent, natural gas, copper, and soybeans
            are filled at the MT5 price. The stop keeps the same distance, rescaled when the broker quotes a
            different unit. On those markets one pip is 0.01% of price, because the 40-pip and 50-pip rules were
            written for currencies.
          </p>
        </article>
      </div>
    </>
  );
}
