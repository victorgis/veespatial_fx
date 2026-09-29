import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { desk } from "../api";
import { useAuth } from "../auth";
import type { Market, Settings } from "../types";
import { LotTable } from "../ui";

export function SettingsPage() {
  const { me, refresh, signOut } = useAuth();
  const navigate = useNavigate();
  const [markets, setMarkets] = useState<Market[]>([]);
  const [form, setForm] = useState<Settings | null>(me?.settings ?? null);
  const [watch, setWatch] = useState<string[]>(me?.watchlist ?? []);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    desk.markets().then(setMarkets).catch(() => setMarkets([]));
  }, []);

  if (!me || !form) return null;
  const current = form;
  const who = me;

  function patch(partial: Partial<Settings>) {
    setForm((previous) => (previous ? { ...previous, ...partial } : previous));
  }

  function toggle(list: string[], id: string, on: boolean) {
    return on ? Array.from(new Set([...list, id])) : list.filter((item) => item !== id);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const result = await desk.saveSettings({
        trade_mode: current.trade_mode,
        account_type: current.account_type,
        platform: current.platform,
        risk_percent: Number(current.risk_percent),
        max_lot: Number(current.max_lot),
        planning_balance: Number(current.planning_balance),
        max_open_trades: Math.min(5, Math.max(1, Math.round(Number(current.max_open_trades) || 3))),
        enabled_symbols: current.enabled_symbols,
        alias_overrides: current.alias_overrides,
        onboarding_done: true,
        risk_accepted: current.risk_accepted,
        trust_platform_size: current.trust_platform_size,
      });
      if (who.user.is_admin) await desk.saveWatchlist(watch);
      if (result.ea_key) setKey(result.ea_key);
      setSaved("Saved.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="page-head">
        <h1>Settings</h1>
        <p className="lede">These choices apply only to your account. The Telegram channel still posts every watched market.</p>
      </header>
      <form className="stack" onSubmit={onSubmit}>
        <section className="card">
          <h2>How trades are placed</h2>
          <div className="choices">
            <button className={`choice ${form.trade_mode === "auto" ? "on" : ""}`} type="button" onClick={() => patch({ trade_mode: "auto", platform: form.platform === "xm" ? "mt5" : form.platform })}>
              <b>Automatic</b>
              <small>The copier places the order. Needs MT4 or MT5 running.</small>
            </button>
            <button className={`choice ${form.trade_mode === "manual" ? "on" : ""}`} type="button" onClick={() => patch({ trade_mode: "manual" })}>
              <b>Signals only</b>
              <small>You place each trade yourself.</small>
            </button>
          </div>
          <label className="field" style={{ marginTop: 14 }}>
            <span>Platform</span>
            <select value={form.platform} onChange={(e) => patch({ platform: e.target.value as Settings["platform"] })}>
              <option value="mt5">MetaTrader 5</option>
              <option value="mt4">MetaTrader 4</option>
              <option value="xm" disabled={form.trade_mode === "auto"}>XM app (signals only)</option>
            </select>
          </label>
        </section>
        <section className="card">
          <h2>Account type</h2>
          <div className="choices">
            <button className={`choice ${form.account_type === "standard" ? "on" : ""}`} type="button" onClick={() => patch({ account_type: "standard" })}>
              <b>Standard · 1 lot = 100,000</b>
            </button>
            <button className={`choice ${form.account_type === "micro" ? "on" : ""}`} type="button" onClick={() => patch({ account_type: "micro" })}>
              <b>Micro · 1 lot = 1,000</b>
            </button>
          </div>
          <LotTable />
        </section>
        <section className="card">
          <h2>Risk</h2>
          <label className="field">
            <span>Risk per trade, percent</span>
            <input type="number" min={0.1} max={5} step={0.1} value={form.risk_percent} onChange={(e) => patch({ risk_percent: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span>Planning balance, used until the platform reports one</span>
            <input type="number" min={0} step={1} value={form.planning_balance} onChange={(e) => patch({ planning_balance: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span>Maximum lots on this account</span>
            <input type="number" min={0.01} max={100} step={0.01} value={form.max_lot} onChange={(e) => patch({ max_lot: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span>Automatic trades open at once</span>
            <input
              type="number"
              min={1}
              max={5}
              step={1}
              value={form.max_open_trades ?? 3}
              onChange={(e) => patch({ max_open_trades: Number(e.target.value) })}
            />
          </label>
          <p className="help">3 is the usual number, and 5 is the most. Further signals still go to Telegram immediately. They are not sent to the platform until an automatic trade closes.</p>
        </section>
        <section className="card">
          <h2>Markets you trade</h2>
          <p className="help">Unchecked markets stay off your desk and are not sent to your platform.</p>
          <div className="checkgrid">
            {markets.map((market) => (
              <label key={market.id} className="check">
                <input
                  type="checkbox"
                  checked={form.enabled_symbols.includes(market.id)}
                  onChange={(e) => patch({ enabled_symbols: toggle(form.enabled_symbols, market.id, e.target.checked) })}
                />
                <span>
                  <b>{market.display}</b>
                  <small className="faint" style={{ display: "block" }}>{market.pair}{market.mt5_only ? " · MT5" : ""}</small>
                </span>
              </label>
            ))}
          </div>
        </section>
        {me.user.is_admin ? (
          <section className="card">
            <h2>Markets the bot watches</h2>
            <p className="help">Unchecked markets are not scanned and are not posted to Telegram.</p>
            <div className="checkgrid">
              {markets.map((market) => (
                <label key={market.id} className="check">
                  <input
                    type="checkbox"
                    checked={watch.includes(market.id)}
                    onChange={(e) => setWatch((current) => toggle(current, market.id, e.target.checked))}
                  />
                  <span>{market.display}</span>
                </label>
              ))}
            </div>
          </section>
        ) : null}
        <section className="card">
          <h2>Advanced</h2>
          <label className="check">
            <input type="checkbox" checked={form.trust_platform_size} onChange={(e) => patch({ trust_platform_size: e.target.checked })} />
            <span>Use the contract size reported by my platform, even if it disagrees with the account type I picked.</span>
          </label>
          <label className="field" style={{ marginTop: 14 }}>
            <span>Extra symbol names, one per line, like oil=OILCash.pro</span>
            <textarea value={form.alias_overrides} onChange={(e) => patch({ alias_overrides: e.target.value })} />
          </label>
        </section>
        {key ? (
          <div className="banner warn">
            <strong>Save this copier key. It will not be shown again.</strong>
            <p className="keybox">{key}</p>
          </div>
        ) : null}
        {error ? <p className="error">{error}</p> : null}
        {saved ? <p className="help">{saved}</p> : null}
        <div className="actions">
          <button className="btn primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save settings"}</button>
          <button
            className="btn ghost"
            type="button"
            onClick={() => {
              signOut();
              navigate("/login");
            }}
          >
            Log out
          </button>
        </div>
      </form>
    </>
  );
}
