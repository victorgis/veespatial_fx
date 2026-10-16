import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { desk } from "../api";
import { outcomeLabel, when } from "../format";
import type { Signal } from "../types";
import { Banner, Compare, CopyButton, Prices, SignalCard, SizeBlock } from "../ui";

const FILTERS = [
  ["all", "All"],
  ["currency", "Currencies"],
  ["metal", "Gold"],
  ["energy", "Oil and Brent"],
] as const;

export function Signals() {
  const [rows, setRows] = useState<Signal[] | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("all");
  const [error, setError] = useState("");

  useEffect(() => {
    desk.signals().then(setRows).catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load."));
  }, []);

  const visible = (rows || []).filter((row) => filter === "all" || row.group === filter);
  return (
    <>
      <header className="page-head">
        <h1>Signals</h1>
        <p className="lede">The same idea for every account. The size on each card is yours.</p>
      </header>
      <div className="pills">
        {FILTERS.map(([id, label]) => (
          <button key={id} className={`pill ${filter === id ? "on" : ""}`} type="button" onClick={() => setFilter(id)}>
            {label}
          </button>
        ))}
      </div>
      {error ? <p className="error">{error}</p> : null}
      {!rows ? <p className="muted">Loading signals…</p> : null}
      <div className="stack">
        {visible.map((signal) => <SignalCard key={signal.id} signal={signal} />)}
        {rows && visible.length === 0 ? <p className="empty">Nothing in this group yet.</p> : null}
      </div>
    </>
  );
}

export function SignalDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [signal, setSignal] = useState<Signal | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    desk.signal(Number(id)).then(setSignal).catch((err: unknown) => setError(err instanceof Error ? err.message : "Not found."));
  }, [id]);

  async function mark(action: "you_placed" | "you_skipped") {
    if (!signal) return;
    const next = await desk.mark(signal.id, action);
    setSignal(next);
  }

  if (error) return <p className="error">{error}</p>;
  if (!signal || !signal.quote) return <p className="muted">Loading…</p>;
  const canMark = signal.delivery_status !== "placed" && signal.delivery_status !== "off";

  return (
    <>
      <button className="btn ghost" type="button" onClick={() => navigate(-1)}>Back</button>
      <header className="page-head" style={{ marginTop: 16 }}>
        <p className="steps">{signal.side === "buy" ? "Buy" : "Sell"} · {outcomeLabel(signal.status)} · {when(signal.created_at)}</p>
        <h1>{signal.display}</h1>
        <p className="lede">{signal.pair}</p>
      </header>
      <div className="stack">
        {signal.status === "exit" ? <Banner tone="warn" title="Close this trade" children="The opposite ICWR signal printed. An automatic account is told to flatten. If you placed it yourself, close it at the market." /> : null}
        {signal.mt5_only ? <Banner tone="warn" title="This cash market is on MT5" children={signal.note} /> : null}
        {signal.quote.blocked ? <Banner tone="bad" title="Check the account type" children={signal.quote.reason || undefined} /> : null}
        <article className={`card signal ${signal.side}`}>
          <Prices signal={signal} />
          <SizeBlock signal={signal} />
          <Compare quote={signal.quote} />
          <div className="actions">
            <CopyButton text={signal.copy_text} />
            {canMark ? (
              <>
                <button className="btn ghost" type="button" onClick={() => mark("you_placed")}>I placed this</button>
                <button className="btn ghost" type="button" onClick={() => mark("you_skipped")}>Skip</button>
              </>
            ) : null}
          </div>
          {signal.delivery_message ? <p className="help">{signal.delivery_message}</p> : null}
          {signal.ticket ? <p className="help">Ticket {signal.ticket}{signal.fill_price != null ? ` at ${signal.fill_price}` : ""}.</p> : null}
        </article>
        <article className="card">
          <h2>Why this signal</h2>
          <p>{signal.rationale}</p>
          <p className="help">{signal.source}</p>
        </article>
        <article className="card">
          <h2>Place it yourself</h2>
          <ol className="guide">
            <li>Open {signal.display} on MT5, MT4, or the XM app. For oil, search OILCash. For Brent, search BRENTCash.</li>
            <li>Choose {signal.side === "buy" ? "Buy" : "Sell"} and enter the lot size above for your account type.</li>
            <li>{signal.tp > 0 ? "Set the stop and the target to the prices on this page before you confirm." : "Set the stop to the price on this page. Do not set a take profit. Close the trade when the opposite signal prints, or when the stop is hit."}</li>
            <li>Come back and mark it placed, so your journal stays honest.</li>
          </ol>
        </article>
      </div>
    </>
  );
}

export function Journal() {
  const [rows, setRows] = useState<Signal[] | null>(null);
  useEffect(() => {
    desk.signals().then(setRows);
  }, []);
  return (
    <>
      <header className="page-head">
        <h1>Journal</h1>
        <p className="lede">What happened to each signal on your account.</p>
      </header>
      {!rows ? <p className="muted">Loading journal…</p> : null}
      <div className="stack">
        {(rows || []).map((signal) => <SignalCard key={signal.id} signal={signal} />)}
        {rows && rows.length === 0 ? <p className="empty">No signals yet.</p> : null}
      </div>
    </>
  );
}
