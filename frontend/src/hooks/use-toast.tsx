import * as React from "react";

export interface Toast {
  id: string;
  title?: string;
  description?: string;
  variant?: "default" | "destructive";
}

interface ToastState {
  toasts: Toast[];
}

type Action =
  | { type: "ADD_TOAST"; toast: Toast }
  | { type: "DISMISS_TOAST"; toastId: string };

let count = 0;
function genId() {
  return String(++count);
}

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

function reducer(state: ToastState, action: Action): ToastState {
  switch (action.type) {
    case "ADD_TOAST":
      return { ...state, toasts: [action.toast, ...state.toasts].slice(0, 5) };
    case "DISMISS_TOAST":
      return {
        ...state,
        toasts: state.toasts.filter((t) => t.id !== action.toastId),
      };
  }
}

const ToastContext = React.createContext<{
  state: ToastState;
  dispatch: React.Dispatch<Action>;
} | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = React.useReducer(reducer, { toasts: [] });
  return (
    <ToastContext.Provider value={{ state, dispatch }}>
      {children}
    </ToastContext.Provider>
  );
}

export function toast(props: Omit<Toast, "id">) {
  const id = genId();
  const event = new CustomEvent("toast-add", {
    detail: { ...props, id },
  });
  window.dispatchEvent(event);
  const timeout = setTimeout(() => {
    const dismissEvent = new CustomEvent("toast-dismiss", {
      detail: { toastId: id },
    });
    window.dispatchEvent(dismissEvent);
    toastTimeouts.delete(id);
  }, 5000);
  toastTimeouts.set(id, timeout);
  return id;
}

export function useToast() {
  const ctx = React.useContext(ToastContext);
  if (!ctx) {
    return {
      toasts: [],
      toast,
      dismiss: (_id: string) => {},
    };
  }

  React.useEffect(() => {
    const handleAdd = (e: Event) => {
      const detail = (e as CustomEvent).detail as Toast;
      ctx.dispatch({ type: "ADD_TOAST", toast: detail });
    };
    const handleDismiss = (e: Event) => {
      const detail = (e as CustomEvent).detail as { toastId: string };
      ctx.dispatch({ type: "DISMISS_TOAST", toastId: detail.toastId });
    };
    window.addEventListener("toast-add", handleAdd);
    window.addEventListener("toast-dismiss", handleDismiss);
    return () => {
      window.removeEventListener("toast-add", handleAdd);
      window.removeEventListener("toast-dismiss", handleDismiss);
    };
  }, [ctx]);

  return {
    ...ctx.state,
    toast,
    dismiss: (id: string) => {
      const event = new CustomEvent("toast-dismiss", { detail: { toastId: id } });
      window.dispatchEvent(event);
    },
  };
}
