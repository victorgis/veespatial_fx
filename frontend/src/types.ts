export type Settings = {
  trade_mode: "auto" | "manual";
  account_type: "standard" | "micro";
  platform: "mt4" | "mt5" | "xm";
  risk_percent: number;
  max_lot: number;
  planning_balance: number;
  max_open_trades: number;
  enabled_symbols: string[];
  alias_overrides: string;
  onboarding_done: boolean;
  risk_accepted: boolean;
  trust_platform_size: boolean;
  ea_key_prefix: string | null;
};

export type Connection = {
  online: boolean;
  last_seen: string | null;
  broker: string | null;
  account_login: string | null;
  balance: number | null;
  equity: number | null;
  currency: string;
  ea_platform: string | null;
  fx_symbol: string | null;
  fx_contract: number | null;
  detected_account_type: "standard" | "micro" | null;
  mismatch: boolean;
  mismatch_message: string | null;
};

export type Me = {
  user: { id: number; email: string; name: string; is_admin: boolean };
  settings: Settings;
  connection: Connection;
  telegram_configured: boolean;
  telegram_error: string;
  status_line: string;
  watchlist: string[];
};

export type Quote = {
  lots: number | null;
  units: number | null;
  unit: string;
  risk_cash: number;
  currency: string;
  min_lot: number;
  too_small: boolean;
  reason: string | null;
  approximate: boolean;
  standard_lots: number | null;
  micro_lots: number | null;
  scales_with_account: boolean;
  uses_live_contract: boolean;
  contract_size: number | null;
  balance_source: "platform" | "planning";
  balance: number;
  blocked: boolean;
};

export type Signal = {
  id: number;
  symbol_id: string;
  display: string;
  pair: string;
  group: string;
  digits: number;
  unit: string;
  mt5_only: boolean;
  note: string;
  side: "buy" | "sell";
  entry: number;
  sl: number;
  tp: number;
  rsi: number;
  status: string;
  rationale: string;
  source: string;
  created_at: string;
  closed_at: string | null;
  close_price: number | null;
  delivery_id: number | null;
  delivery_status: string | null;
  delivery_message: string | null;
  ticket: string | null;
  fill_price: number | null;
  placed_lots: number | null;
  broker_symbol: string | null;
  quote: Quote | null;
  copy_text: string;
};

export type Dashboard = {
  me: Me;
  scan: {
    started_at: string | null;
    finished_at: string | null;
    ok: boolean | null;
    message: string;
    signals_created: number;
  };
  signals: Signal[];
  recent: Signal[];
};

export type Market = {
  id: string;
  display: string;
  pair: string;
  group: string;
  mt5_only: boolean;
  aliases: string[];
  scales_with_account: boolean;
  unit: string;
  note: string;
  contract_standard: number;
  contract_micro: number;
};
