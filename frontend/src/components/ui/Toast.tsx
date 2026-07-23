/**
 * Sparse toast system (SPEC §23 — no toast for small copy actions).
 * Used only for meaningful async outcomes: failures, queue-level changes.
 */

import * as RadixToast from "@radix-ui/react-toast";
import { create } from "zustand";
import styles from "./ui.module.css";

export interface ToastItem {
  id: number;
  title: string;
  description?: string;
  kind: "info" | "success" | "error";
}

interface ToastStore {
  toasts: ToastItem[];
  push: (toast: Omit<ToastItem, "id">) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  push: (toast) =>
    set((state) => ({ toasts: [...state.toasts.slice(-3), { ...toast, id: nextId++ }] })),
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  info: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, kind: "info" }),
  success: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, kind: "success" }),
  error: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, kind: "error" }),
};

export function Toaster() {
  const { toasts, dismiss } = useToastStore();
  return (
    <RadixToast.Provider swipeDirection="right" duration={5000}>
      {toasts.map((item) => (
        <RadixToast.Root
          key={item.id}
          className={`${styles.toastRoot} ${
            item.kind === "error"
              ? styles.toastError
              : item.kind === "success"
                ? styles.toastSuccess
                : ""
          }`}
          onOpenChange={(open) => {
            if (!open) dismiss(item.id);
          }}
        >
          <RadixToast.Title className={styles.toastTitle}>{item.title}</RadixToast.Title>
          {item.description ? (
            <RadixToast.Description className={styles.toastDescription}>
              {item.description}
            </RadixToast.Description>
          ) : null}
        </RadixToast.Root>
      ))}
      <RadixToast.Viewport className={styles.toastViewport} />
    </RadixToast.Provider>
  );
}
