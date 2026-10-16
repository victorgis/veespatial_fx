export function price(value: number, digits: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function lots(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function money(value: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
}

export function when(iso: string | null): string {
  if (!iso) return "not yet";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function deliveryLabel(status: string | null): string {
  switch (status) {
    case "queued":
      return "Waiting for your platform";
    case "for_you":
      return "For you to place";
    case "paused":
      return "Paused";
    case "placed":
      return "Placed on platform";
    case "sl_to_entry":
      return "Stop loss at entry (+$2 profit)";
    case "not_placed":
      return "Not placed";
    case "you_placed":
      return "You placed this";
    case "you_skipped":
      return "You skipped this";
    case "off":
      return "Turned off for you";
    case "capped":
      return "At your open-trade limit";
    case "close_queued":
      return "Closing on your platform";
    case "closed":
      return "Closed on your platform";
    case "cancelled":
      return "Not sent";
    default:
      return status || "Open";
  }
}

export function outcomeLabel(status: string): string {
  switch (status) {
    case "active":
      return "Open";
    case "target":
      return "Take profit hit (1:1)";
    case "stopped":
      return "Stopped out";
    case "breakeven":
      return "Breakeven (SL at entry)";
    case "expired":
      return "Expired";
    case "exit":
      return "Closed on the opposite signal";
    default:
      return status;
  }
}
