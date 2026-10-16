import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { desk, getToken } from "./api";

export type Toast = {
  id: string;
  type: "placed" | "be" | "tp" | "exit" | "info";
  title: string;
  message: string;
  timestamp: Date;
};

type NotificationContextType = {
  toasts: Toast[];
  removeToast: (id: string) => void;
  permission: NotificationPermission;
  requestPermission: () => Promise<void>;
};

const NotificationContext = createContext<NotificationContextType>({
  toasts: [],
  removeToast: () => {},
  permission: "default",
  requestPermission: async () => {},
});

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [permission, setPermission] = useState<NotificationPermission>(
    typeof window !== "undefined" && "Notification" in window ? Notification.permission : "default"
  );
  const seenRef = useRef<{
    placed: Set<string>;
    be: Set<string>;
    tp: Set<string>;
    exit: Set<string>;
  }>({
    placed: new Set(),
    be: new Set(),
    tp: new Set(),
    exit: new Set(),
  });
  const initialLoadRef = useRef(true);

  async function requestPermission() {
    if (typeof window !== "undefined" && "Notification" in window) {
      try {
        const res = await Notification.requestPermission();
        setPermission(res);
        if (res === "granted") {
          addToast({
            type: "info",
            title: "🔔 Desktop Notifications Enabled",
            message: "You will receive desktop alerts when trades open, lock at breakeven, and hit take profit.",
          });
        }
      } catch (err) {
        console.error("Failed to request notification permission", err);
      }
    }
  }

  function addToast(toast: Omit<Toast, "id" | "timestamp">) {
    const id = `${Date.now()}-${Math.random()}`;
    const newToast: Toast = { ...toast, id, timestamp: new Date() };
    setToasts((prev) => [newToast, ...prev].slice(0, 5));

    // Also fire Desktop OS Notification if permitted
    if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
      try {
        new Notification(toast.title, {
          body: toast.message,
          icon: "/favicon.ico",
        });
      } catch {
        // Ignore notification constructor error
      }
    }

    // Auto dismiss in-app toast after 8 seconds
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 8000);
  }

  function removeToast(id: string) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  // Poll for signal updates every 8 seconds
  useEffect(() => {
    let mounted = true;

    async function checkUpdates() {
      // Must check if user is logged in before polling
      const token = getToken();
      if (!token) return;

      try {
        const signals = await desk.signals();
        if (!mounted || !signals) return;

        for (const sig of signals) {
          const sigKey = `${sig.id}`;
          const isPlaced = sig.delivery_status === "placed" || sig.ticket != null;
          const isBE =
            (sig.delivery_message && sig.delivery_message.toLowerCase().includes("stop loss moved to entry")) ||
            sig.delivery_status === "sl_to_entry" ||
            (sig.status === "active" && sig.sl === sig.entry);
          const isTP = sig.status === "target";
          const isExit = sig.status === "exit";

          if (initialLoadRef.current) {
            // Populate seen on initial load so we don't spam toasts on page reload
            if (isPlaced) seenRef.current.placed.add(sigKey);
            if (isBE) seenRef.current.be.add(sigKey);
            if (isTP) seenRef.current.tp.add(sigKey);
            if (isExit) seenRef.current.exit.add(sigKey);
            continue;
          }

          // Check if newly placed
          if (isPlaced && !seenRef.current.placed.has(sigKey)) {
            seenRef.current.placed.add(sigKey);
            addToast({
              type: "placed",
              title: `🚀 Trade Placed: ${sig.display}`,
              message: `${sig.side.toUpperCase()} order placed on platform.${sig.ticket ? ` Ticket #${sig.ticket}` : ""}${sig.fill_price ? ` at ${sig.fill_price}` : ""}.`,
            });
          }

          // Check if Stop Loss moved to Entry (Breakeven)
          if (isBE && !seenRef.current.be.has(sigKey)) {
            seenRef.current.be.add(sigKey);
            addToast({
              type: "be",
              title: `🛡️ Stop Loss Moved to Entry: ${sig.display}`,
              message: `Profit reached +$2.00 on MT5! Stop loss safely locked at entry (${sig.entry}).`,
            });
          }

          // Check if Take Profit hit
          if (isTP && !seenRef.current.tp.has(sigKey)) {
            seenRef.current.tp.add(sigKey);
            addToast({
              type: "tp",
              title: `🎯 Take Profit Hit: ${sig.display}!`,
              message: `1:1 Target achieved! Profit locked in at ${sig.close_price || sig.tp}.`,
            });
          }

          if (isExit && !seenRef.current.exit.has(sigKey)) {
            seenRef.current.exit.add(sigKey);
            addToast({
              type: "exit",
              title: `Opposite signal: ${sig.display}`,
              message: `Close the ${sig.side} trade. The ICWR signal flipped${sig.close_price ? ` at ${sig.close_price}` : ""}.`,
            });
          }
        }

        if (initialLoadRef.current) {
          initialLoadRef.current = false;
        }
      } catch {
        // Scan polling error, ignore
      }
    }

    checkUpdates();
    const interval = window.setInterval(checkUpdates, 8000);
    return () => {
      mounted = false;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <NotificationContext.Provider value={{ toasts, removeToast, permission, requestPermission }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={removeToast} />
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  return useContext(NotificationContext);
}

function ToastContainer({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-container" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast-card toast-${toast.type}`}>
          <div className="toast-header">
            <strong>{toast.title}</strong>
            <button
              className="toast-close"
              type="button"
              aria-label="Dismiss notification"
              onClick={() => onDismiss(toast.id)}
            >
              ×
            </button>
          </div>
          <p className="toast-body">{toast.message}</p>
        </div>
      ))}
    </div>
  );
}
