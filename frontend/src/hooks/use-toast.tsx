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
  toast: (props: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
} | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = React.useReducer(reducer, { toasts: [] });
  const timeoutRefs = React.useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  React.useEffect(() => {
    return () => {
      timeoutRefs.current.forEach((t) => clearTimeout(t));
      timeoutRefs.current.clear();
    };
  }, []);

  const toastFn = React.useCallback((props: Omit<Toast, "id">) => {
    const id = genId();
    dispatch({ type: "ADD_TOAST", toast: { ...props, id } });
    const timeout = setTimeout(() => {
      dispatch({ type: "DISMISS_TOAST", toastId: id });
      timeoutRefs.current.delete(id);
    }, 5000);
    timeoutRefs.current.set(id, timeout);
    return id;
  }, []);

  const dismissFn = React.useCallback((id: string) => {
    dispatch({ type: "DISMISS_TOAST", toastId: id });
    const t = timeoutRefs.current.get(id);
    if (t) {
      clearTimeout(t);
      timeoutRefs.current.delete(id);
    }
  }, []);

  const ctx = React.useMemo(() => ({
    state,
    dispatch,
    toast: toastFn,
    dismiss: dismissFn,
  }), [state, toastFn, dismissFn]);

  return (
    <ToastContext.Provider value={ctx}>
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
    toast: ctx.toast,
    dismiss: ctx.dismiss,
  };
}
