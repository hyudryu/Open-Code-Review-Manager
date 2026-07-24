import * as RadixSwitch from "@radix-ui/react-switch";
import styles from "./ui.module.css";

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  "aria-label"?: string;
  id?: string;
}

export function Switch({ checked, onCheckedChange, disabled, ...rest }: SwitchProps) {
  return (
    <RadixSwitch.Root
      className={styles.switchRoot}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      {...rest}
    >
      <RadixSwitch.Thumb className={styles.switchThumb} />
    </RadixSwitch.Root>
  );
}
