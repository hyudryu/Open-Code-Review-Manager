import styles from "./ui.module.css";

export function Skeleton({
  width,
  height = 14,
  style,
}: {
  width?: number | string;
  height?: number | string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={styles.skeleton}
      aria-hidden="true"
      style={{
        width: width ?? "100%",
        height,
        ...style,
      }}
    />
  );
}
