import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { desk } from "../api";
import { useAuth } from "../auth";
import { money } from "../format";
import type { Settings } from "../types";
import { LotTable } from "../ui";

export function Setup() {
  const { me, refresh } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [tradeMode, setTradeMode] = useState<Settings["trade_mode"]>(me?.settings.trade_mode ?? "manual");
  const [accountType, setAccountType] = useState<Settings["account_type"]>(me?.settings.account_type ?? "standard");
  const [platform, setPlatform] = useState<Settings["platform"]>(me?.settings.platform ?? "mt5");
  const [risk, setRisk] = useState(me?.settings.risk_percent ?? 0.5);
  const [balance, setBalance] = useState(me?.settings.planning_balance ?? 1000);
  const [maxLot, setMaxLot] = useState(me?.settings.max_lot ?? 0.5);
  const [maxOpen, setMaxOpen] = useState(me?.settings.max_open_trades ?? 3);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState<string | null>(null);

  function chooseAccount(next: Settings["account_type"]) {
    setMaxLot((current) => {
      if (current === 0.5 || current === 50) return next === "micro" ? 50 : 0.5;
      return current;
    });
    setAccountType(next);
  }

  async function finish() {
    if (!me) return;
    setBusy(true);
    setError("");
    try {
      const saved = await desk.saveSettings({
        trade_mode: tradeMode,
        account_type: accountType,
        platform: tradeMode === "auto" && platform === "xm" ? "mt5" : platform,
        risk_percent: risk,
        max_lot: maxLot,
        planning_balance: balance,
        max_open_trades: Math.min(5, Math.max(1, Math.round(maxOpen) || 3)),
        enabled_symbols: me.settings.enabled_symbols,
        alias_overrides: me.settings.alias_overrides,
        onboarding_done: true,
        risk_accepted: true,
        trust_platform_size: false,
      });
      await refresh();
      if (saved.ea_key) {
        setKey(saved.ea_key);
        setStep(4);
      } else {
        navigate("/");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const riskCash = (balance * risk) / 100;
  const platforms: { id: Settings["platform"]; title: string; body: string }[] =
    tradeMode === "auto"
      ? [
          { id: "mt5", title: "MetaTrader 5", body: "Use this for OILCash and BRENTCash. Gold and forex work here too." },
          { id: "mt4", title: "MetaTrader 4", body: "Forex and gold. XM does not list cash oil or Brent on MT4." },
        ]
      : [
          { id: "mt5", title: "MetaTrader 5", body: "Place the signal yourself on the MT5 ticket." },
          { id: "mt4", title: "MetaTrader 4", body: "Place the signal yourself. Cash oil and Brent are not on MT4." },
          { id: "xm", title: "XM app", body: "Place the signal in XM’s own app. The app cannot run the copier." },
        ];

  return (
    <main className="wizard">
      <p className="steps">Step {Math.min(step + 1, 4)} of 4</p>
      {step === 0 ? (
        <>
          <h1>How should a signal become a trade?</h1>
          <p className="lede">You can change this later. Other people on this desk choose for themselves.</p>
          <div className="choices" style={{ marginTop: 18 }}>
            <button className={`choice ${tradeMode === "auto" ? "on" : ""}`} type="button" onClick={() => setTradeMode("auto")}>
              <b>Automatic</b>
              <small>A copier inside MT4 or MT5 places the order on your XM account. Leave the platform open, on your computer or a small VPS.</small>
            </button>
            <button className={`choice ${tradeMode === "manual" ? "on" : ""}`} type="button" onClick={() => setTradeMode("manual")}>
              <b>Signals only</b>
              <small>The signal arrives here and in Telegram. You place it yourself on MT4, MT5, or the XM app.</small>
            </button>
          </div>
        </>
      ) : null}
      {step === 1 ? (
        <>
          <h1>Which XM account is this?</h1>
          <p className="lede">The lot number you type, and the lot number the copier sends, depends on this.</p>
          <div className="choices" style={{ marginTop: 18 }}>
            <button className={`choice ${accountType === "standard" ? "on" : ""}`} type="button" onClick={() => chooseAccount("standard")}>
              <b>Standard</b>
              <small>1 lot = 100,000. One pip on 1 lot of EURUSD is about $10.</small>
            </button>
            <button className={`choice ${accountType === "micro" ? "on" : ""}`} type="button" onClick={() => chooseAccount("micro")}>
              <b>Micro</b>
              <small>1 lot = 1,000. The same position uses a lot number 100 times larger. One pip on 1 lot of EURUSD is about $0.10.</small>
            </button>
          </div>
          <div className="card" style={{ marginTop: 14 }}>
            <LotTable />
            <p className="help">Gold scales the same way on XM. Cash oil does not: 1 lot stays 100 barrels on both account types.</p>
          </div>
        </>
      ) : null}
      {step === 2 ? (
        <>
          <h1>How much can one stop lose?</h1>
          <label className="field">
            <span>Risk per trade, {risk.toFixed(1)}%</span>
            <input type="range" min={0.1} max={2} step={0.1} value={risk} onChange={(e) => setRisk(Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Balance to plan with, until the platform connects</span>
            <input type="number" min={0} step="1" value={balance} onChange={(e) => setBalance(Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Maximum size, in lots on this account</span>
            <input type="number" min={0.01} max={100} step="0.01" value={maxLot} onChange={(e) => setMaxLot(Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Automatic trades open at once, {maxOpen}</span>
            <input type="range" min={1} max={5} step={1} value={maxOpen} onChange={(e) => setMaxOpen(Number(e.target.value))} />
          </label>
          <p className="lede">
            On {money(balance || 0)}, {risk.toFixed(1)}% is {money(riskCash || 0)}. That is the most the desk will aim to lose if the stop is hit.
            Automatic accounts stop at {maxOpen} open trades. Every signal still goes to Telegram.
          </p>
        </>
      ) : null}
      {step === 3 ? (
        <>
          <h1>Where will you trade?</h1>
          <div className="choices">
            {platforms.map((item) => (
              <button key={item.id} className={`choice ${platform === item.id ? "on" : ""}`} type="button" onClick={() => setPlatform(item.id)}>
                <b>{item.title}</b>
                <small>{item.body}</small>
              </button>
            ))}
          </div>
          <label className="check" style={{ marginTop: 16 }}>
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
            <span>I understand a stop can be skipped in a fast market, and I can lose more than the planned amount. I am responsible for the trades on my account.</span>
          </label>
          {error ? <p className="error">{error}</p> : null}
        </>
      ) : null}
      {step === 4 && key ? (
        <>
          <h1>Save this copier key</h1>
          <p className="lede">It is shown once. Paste it into SignalBridge on the chart. You can create a new one later from the guide, which stops the old key.</p>
          <p className="keybox">{key}</p>
          <div className="actions">
            <button className="btn primary" type="button" onClick={() => navigator.clipboard.writeText(key)}>Copy key</button>
            <button className="btn ghost" type="button" onClick={() => navigate("/guide")}>How to attach it</button>
          </div>
        </>
      ) : null}
      {step < 4 ? (
        <div className="actions">
          {step > 0 ? (
            <button className="btn ghost" type="button" onClick={() => setStep((s) => s - 1)}>Back</button>
          ) : null}
          {step < 3 ? (
            <button className="btn primary" type="button" onClick={() => setStep((s) => s + 1)}>Continue</button>
          ) : (
            <button className="btn primary" type="button" disabled={!accepted || busy} onClick={finish}>
              {busy ? "Saving…" : "Save and continue"}
            </button>
          )}
        </div>
      ) : null}
    </main>
  );
}
