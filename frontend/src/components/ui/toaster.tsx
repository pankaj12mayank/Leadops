import { useToast } from "@/hooks/use-toast";
import { Toast } from "./toast";

export function Toaster() {
  const { toasts, dismiss } = useToast();
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <Toast key={t.id} id={t.id} title={t.title} description={t.description} variant={t.variant} onDismiss={dismiss} />
      ))}
    </div>
  );
}
