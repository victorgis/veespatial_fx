import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "./auth";
import { useNotifications } from "./notifications";

const LINKS = [
  ["/", "Home"],
  ["/signals", "Signals"],
  ["/journal", "Journal"],
  ["/guide", "Guide"],
  ["/settings", "Settings"],
] as const;

export function Shell() {
  const { me } = useAuth();
  const { permission, requestPermission } = useNotifications();
  if (!me?.settings.onboarding_done) {
    return (
      <div>
        <Outlet />
      </div>
    );
  }
  const mode = me.settings.trade_mode === "auto" ? "Automatic" : "Signals only";
  const account = me.settings.account_type === "micro" ? "Micro · 1 lot = 1,000" : "Standard · 1 lot = 100,000";
  return (
    <div className="shell">
      <aside className="rail">
        <NavLink to="/" className="brand">
          <strong>Signal Desk</strong>
          <span>XM signals, and the option to place them</span>
        </NavLink>
        <nav className="nav">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-foot">
          {permission !== "granted" ? (
            <button
              className="btn ghost"
              type="button"
              style={{ fontSize: 13, padding: "6px 12px", minHeight: 34, borderColor: "var(--brass)", color: "var(--brass)" }}
              onClick={requestPermission}
            >
              🔔 Enable Alerts
            </button>
          ) : (
            <span className="muted" style={{ fontSize: 13 }}>
              🔔 Alerts Active
            </span>
          )}
          <span>
            <i className={`status-dot ${me.connection.online ? "on" : ""}`} /> {mode}
          </span>
          <span className="muted">{account}</span>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <strong>Signal Desk</strong>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {permission !== "granted" ? (
              <button
                className="btn ghost"
                type="button"
                style={{ fontSize: 12, padding: "4px 10px", minHeight: 30, borderColor: "var(--brass)", color: "var(--brass)" }}
                onClick={requestPermission}
              >
                🔔 Alerts
              </button>
            ) : null}
            <span className="muted">
              <i className={`status-dot ${me.connection.online ? "on" : ""}`} /> {mode}
            </span>
          </div>
        </header>
        <div className="content">
          <Outlet />
          <p className="footer-note">
            A stop can be skipped in a fast market, so a trade can lose more than the planned amount. This is a rules
            alert, not a promise of profit.
          </p>
        </div>
        <nav className="bottom-nav">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
