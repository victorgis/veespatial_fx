import { useState } from "react";
import { Link } from "react-router-dom";
import { deliveryLabel, lots, money, outcomeLabel, price, when } from "./format";
import type { Quote, Signal } from "./types";

export function Banner({ tone, title, children }: { tone: "warn" | "bad" | "ok"; title: string; children?: string | null }) {
  return (
    <div className={`banner ${tone}`} role="status">
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

export function Prices({ signal }: { signal: Signal }) {
  return (
    <div className="prices">
      <div className="price"><span>Entry</span><b>{price(signal.entry, signal.digits)}</b></div>
      <div className="price"><span>Stop</span><b>{price(signal.sl, signal.digits)}</b></div>
      <div className="price"><span>Target</span><b>{signal.tp > 0 ? price(signal.tp, signal.digits) : "Opposite signal"}</b></div>
    </div>
  );
}

export function SizeBlock({ signal }: { signal: Signal }) {
  const quote = signal.quote;
  if (!quote) return null;
  const account = quote.balance_source === "platform" ? "your platform balance" : "your planning balance";
  return (
    <div className="size-block">
      <span className="faint">Your size · {account} {money(quote.balance, quote.currency)}</span>
      {quote.lots != null ? (
        <b>
          {lots(quote.lots)} lots
          {quote.units != null ? ` · ${quote.units.toLocaleString("en-US", { maximumFractionDigits: 2 })} ${quote.unit}` : ""}
        </b>
      ) : (
        <b>No automatic size</b>
      )}
      <span className="muted">
        {quote.reason
          ? quote.reason
          : `About ${money(quote.risk_cash, quote.currency)} at risk if the stop is hit.`}
        {quote.uses_live_contract ? " Sized from the contract on your platform." : ""}
        {quote.approximate ? " This cross is an estimate until the platform is connected." : ""}
      </span>
    </div>
  );
}

export function Compare({ quote }: { quote: Quote }) {
  if (!quote.scales_with_account) {
    return (
      <p className="help">
        Standard and micro use the same lot number here. On XM, OILCash and BRENTCash are 100 barrels per lot.
      </p>
    );
  }
  return (
    <div className="compare">
      <div>
        <span>Standard</span>
        <b>{lots(quote.standard_lots)} lots</b>
        <small>1 lot = 100,000</small>
      </div>
      <div>
        <span>Micro</span>
        <b>{lots(quote.micro_lots)} lots</b>
        <small>1 lot = 1,000</small>
      </div>
    </div>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="btn primary"
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          window.setTimeout(() => setDone(false), 1600);
        } catch {
          setDone(false);
        }
      }}
    >
      {done ? "Copied" : "Copy levels"}
    </button>
  );
}

export function SignalCard({ signal }: { signal: Signal }) {
  return (
    <article className={`card signal ${signal.side}`}>
      <div className="kicker">
        <div>
          <strong>{signal.display}</strong>
          <div className="faint">{signal.pair} · {when(signal.created_at)}</div>
        </div>
        <span className={`side ${signal.side}`}>{signal.side === "buy" ? "Buy" : "Sell"}</span>
      </div>
      <Prices signal={signal} />
      <SizeBlock signal={signal} />
      <div className="row-between" style={{ marginTop: 12 }}>
        <span className="muted">{deliveryLabel(signal.delivery_status)} · {outcomeLabel(signal.status)}</span>
        <Link to={`/signals/${signal.id}`}>Open</Link>
      </div>
    </article>
  );
}

export function LotTable() {
  return (
    <table className="lots-table">
      <thead>
        <tr><th></th><th>Standard</th><th>Micro</th></tr>
      </thead>
      <tbody>
        <tr><td>Forex, 1 lot</td><td>100,000</td><td>1,000</td></tr>
        <tr><td>1 pip on 1 lot of EURUSD</td><td>about $10</td><td>about $0.10</td></tr>
        <tr><td>Gold, 1 lot</td><td>100 ounces</td><td>1 ounce</td></tr>
        <tr><td>OILCash / BRENTCash, 1 lot</td><td>100 barrels</td><td>100 barrels</td></tr>
      </tbody>
    </table>
  );
}
