import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import styles from "./ui.module.css";

interface FieldShellProps {
  label: string;
  htmlFor: string;
  help?: string;
  error?: string | null;
  required?: boolean;
  children: ReactNode;
}

/** Persistent visible label + optional help + inline validation (SPEC §23). */
function FieldShell({ label, htmlFor, help, error, required, children }: FieldShellProps) {
  const describedBy: string[] = [];
  if (help) describedBy.push(`${htmlFor}-help`);
  if (error) describedBy.push(`${htmlFor}-error`);
  return (
    <div className={styles.field}>
      <label
        className={`${styles.label} ${required ? styles.labelRequired : ""}`}
        htmlFor={htmlFor}
      >
        {label}
      </label>
      {children}
      {help ? (
        <p className={styles.help} id={`${htmlFor}-help`}>
          {help}
        </p>
      ) : null}
      {error ? (
        <p className={styles.errorText} id={`${htmlFor}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function describedByIds(id: string, help?: string, error?: string | null) {
  const ids: string[] = [];
  if (help) ids.push(`${id}-help`);
  if (error) ids.push(`${id}-error`);
  return ids.length ? ids.join(" ") : undefined;
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  help?: string;
  error?: string | null;
  mono?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, help, error, mono, id, className, required, ...props }, ref) => {
    const autoId = useId();
    const inputId = id ?? autoId;
    return (
      <FieldShell label={label} htmlFor={inputId} help={help} error={error} required={required}>
        <input
          ref={ref}
          id={inputId}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedByIds(inputId, help, error)}
          className={[
            styles.input,
            error ? styles.inputInvalid : "",
            mono ? styles.mono : "",
            className ?? "",
          ]
            .filter(Boolean)
            .join(" ")}
          {...props}
        />
      </FieldShell>
    );
  },
);
Input.displayName = "Input";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  help?: string;
  error?: string | null;
  mono?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, help, error, mono, id, className, required, ...props }, ref) => {
    const autoId = useId();
    const inputId = id ?? autoId;
    return (
      <FieldShell label={label} htmlFor={inputId} help={help} error={error} required={required}>
        <textarea
          ref={ref}
          id={inputId}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedByIds(inputId, help, error)}
          className={[
            styles.textarea,
            error ? styles.textareaInvalid : "",
            mono ? styles.mono : "",
            className ?? "",
          ]
            .filter(Boolean)
            .join(" ")}
          {...props}
        />
      </FieldShell>
    );
  },
);
Textarea.displayName = "Textarea";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  help?: string;
  error?: string | null;
  children: ReactNode;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, help, error, id, className, required, children, ...props }, ref) => {
    const autoId = useId();
    const inputId = id ?? autoId;
    const baseClass = [styles.select, error ? styles.selectInvalid : "", className ?? ""]
      .filter(Boolean)
      .join(" ");

    if (!label) {
      // Inline filter mode: no FieldShell, just a styled select with aria-label
      return (
        <select
          ref={ref}
          id={inputId}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={help ? `${inputId}-help` : undefined}
          className={baseClass}
          {...props}
        >
          {children}
        </select>
      );
    }

    return (
      <FieldShell label={label} htmlFor={inputId} help={help} error={error} required={required}>
        <select
          ref={ref}
          id={inputId}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedByIds(inputId, help, error)}
          className={baseClass}
          {...props}
        >
          {children}
        </select>
      </FieldShell>
    );
  },
);
Select.displayName = "Select";
