import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { Button } from "./Button";
import styles from "./ui.module.css";

export interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: number;
}

/** Radix dialog — focus trap, escape, aria wiring included (SPEC §26). */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  width,
}: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.modalOverlay} />
        <Dialog.Content
          className={styles.modalContent}
          style={width ? { width: `min(${width}px, calc(100vw - 32px))` } : undefined}
        >
          <Dialog.Title className={styles.modalTitle}>{title}</Dialog.Title>
          {description ? (
            <Dialog.Description className={styles.modalDescription}>
              {description}
            </Dialog.Description>
          ) : null}
          {children}
          {footer ? <div className={styles.modalActions}>{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
}

/** Destructive actions are never the default-focused button (SPEC §23). */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive,
  busy,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} autoFocus>
            Cancel
          </Button>
          <Button
            variant={destructive ? "destructive" : "primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working…" : confirmLabel}
          </Button>
        </>
      }
    />
  );
}
