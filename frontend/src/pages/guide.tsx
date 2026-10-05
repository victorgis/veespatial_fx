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
            <li>Read the entry, stop, target, and the lot size for your account type. Copy levels puts them on the clipboard.</li>
            <li>On a standard account, 1 forex lot is 100,000. On a micro account it is 1,000, so the lot number is 100 times larger for the same position.</li>
            <li>For gold, XM uses the same 100× relationship (100 ounces versus 1 ounce). For OILCash and BRENTCash, 1 lot is 100 barrels on both.</li>
            <li>If the card says the minimum lot would risk more than your limit, skip the trade.</li>
          </ol>
        </article>
        <article className="card">
          <h2>How a signal is chosen</h2>
          <p>
            A signal is a 5-minute pullback inside the current trend. The 1-hour chart has to agree: price and the
            50-hour average on the same side of the 200-hour average. The 15-minute swings have to make higher highs
            and higher lows for a buy, or the mirror for a sell. On the 5-minute candle, RSI sits in a pullback band
            and is turning, MACD momentum is turning with the trend, and price has closed back through the 50-bar
            average without running away from it. The stop is beyond that recent swing. The target is 1.8 times as
            far as the stop. A fresh 1-minute candle has to close the same way.
          </p>
          <p>
            Every signal is posted to Telegram as soon as the candle closes. An automatic account does not take all
            of them: three open automatic trades is the usual limit, and five is the most. The rest stay on the
            channel and on this desk for you to place by hand.
          </p>
          <p className="help">
            Prices come from Yahoo Finance real-time market data feed. WTI and Brent are cash CFDs matching
            XM’s OILCash and BRENTCash. The copier skips the order if the broker price has already moved more than a
            quarter of the way to the stop.
          </p>
        </article>
      </div>
    </>
  );
}
