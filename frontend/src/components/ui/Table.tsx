import type { ReactNode } from "react";
import styles from "./ui.module.css";

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>{children}</table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>;
}

export function Tr({
  children,
  onClick,
  selected,
}: {
  children: ReactNode;
  onClick?: () => void;
  selected?: boolean;
}) {
  return (
    <tr
      className={onClick ? styles.rowClickable : undefined}
      onClick={onClick}
      tabIndex={onClick ? 0 : undefined}
      aria-selected={selected || undefined}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      {children}
    </tr>
  );
}

export function Th({ children, style }: { children?: ReactNode; style?: React.CSSProperties }) {
  return <th scope="col" style={style}>{children}</th>;
}

export function Td({
  children,
  colSpan,
  style,
  className,
  title,
}: {
  children?: ReactNode;
  colSpan?: number;
  style?: React.CSSProperties;
  className?: string;
  title?: string;
}) {
  return (
    <td colSpan={colSpan} style={style} className={className} title={title}>
      {children}
    </td>
  );
}
