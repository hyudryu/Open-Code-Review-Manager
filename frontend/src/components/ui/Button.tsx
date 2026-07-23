import { forwardRef, type ButtonHTMLAttributes } from "react";
import styles from "./ui.module.css";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "tertiary"
  | "destructive"
  | "destructive-quiet";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "default" | "small";
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", size = "default", className, type, ...props }, ref) => {
    const variantClass =
      variant === "destructive-quiet" ? styles.destructiveQuiet : styles[variant];
    return (
      <button
        ref={ref}
        type={type ?? "button"}
        className={[
          styles.button,
          variantClass,
          size === "small" ? styles.small : "",
          className ?? "",
        ]
          .filter(Boolean)
          .join(" ")}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
