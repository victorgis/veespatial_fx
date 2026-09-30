import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { desk } from "../api";
import { useAuth } from "../auth";
import { when } from "../format";
import type { Dashboard } from "../types";
import { Banner, SignalCard } from "../ui";

export function Home() {
  const { me, refresh } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);

  function load() {
    return desk.dashboard().then(setData).catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load."));
  }

  useEffect(() => {
    load();
  }, []);

  if (!me || !data) {
    return <p className="muted">{error || "Loading your desk…"}</p>;
  }

  const conn = data.me.connection;
  const auto = me.settings.trade_mode === "auto";

  return (
    <>
      <header className="page-head">
        <h1>{me.user.name.split(" ")[0]}’s desk</h1>
        <p className="lede">{data.me.status_line}</p>
      </header>
      <div className="stack">
        {auto && conn.mismatch && conn.mismatch_message ? <Banner tone="bad" title="Automatic orders are paused" children={conn.mismatch_message} /> : null}
        {auto && !conn.online && !conn.mismatch ? (
          <Banner tone="warn" title="Your platform is not connected">
            Open MT4 or MT5, attach SignalBridge, and leave it running. The guide shows the steps.
          </Banner>
        ) : null}
        {auto && conn.online && !conn.mismatch ? (
          <Banner
            tone="ok"
            title="Platform connected"
            children={`${[conn.account_login, conn.broker].filter(Boolean).join(" at ") || "Heartbeat received."}${conn.balance != null ? ` Balance ${conn.balance.toLocaleString()} ${conn.currency}.` : ""
              }`}
          />
        ) : null}
        {me.user.is_admin && !data.me.telegram_configured ? (
          <Banner tone="warn" title="Telegram is not configured" children="Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID on the server. Signals still appear here." />
        ) : null}
        {me.user.is_admin && data.me.telegram_configured && data.me.telegram_error ? (
          <Banner tone="warn" title="Telegram did not post" children={data.me.telegram_error} />
        ) : null}
        {error ? <p className="error">{error}</p> : null}
        {data.signals.length === 0 ? (
          <div className="card empty" style={{ marginRight: 10 }}>
            <strong>No open signal.</strong>
            <p>{data.scan.message} Last scan {when(data.scan.finished_at)}.</p>
          </div>
        ) : (
          data.signals.map((signal) => <SignalCard key={signal.id} signal={signal} />)
        )}
        {data.recent.length > 0 ? (
          <section>
            <h2>Recently closed</h2>
            <div className="stack">
              {data.recent.slice(0, 3).map((signal) => <SignalCard key={signal.id} signal={signal} />)}
            </div>
            <p><Link to="/journal">Full journal</Link></p>
          </section>
        ) : null}
        <p className="faint">
          Watching {data.me.watchlist.length} markets. {data.scan.message}
          {me.user.is_admin ? (
            <>
              {" "}
              <button
                className="btn ghost"
                type="button"
                disabled={scanning}
                onClick={async () => {
                  setScanning(true);
                  try {
                    await desk.scan();
                    await load();
                    await refresh();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Scan failed.");
                  } finally {
                    setScanning(false);
                  }
                }}
              >
                {scanning ? "Scanning…" : "Scan now"}
              </button>
            </>
          ) : null}
        </p>
      </div>
    </>
  );
}
