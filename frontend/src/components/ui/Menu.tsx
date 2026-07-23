import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";
import styles from "./ui.module.css";

export interface MenuItemDef {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect?: () => void;
  type?: "item" | "separator" | "label";
}

export function Menu({
  trigger,
  items,
  align = "end",
  ariaLabel,
}: {
  trigger: ReactNode;
  items: MenuItemDef[];
  align?: "start" | "center" | "end";
  ariaLabel?: string;
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild aria-label={ariaLabel}>
        {trigger}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className={styles.menuContent} align={align} sideOffset={4}>
          {items.map((item) => {
            if (item.type === "separator")
              return <DropdownMenu.Separator key={item.key} className={styles.menuSeparator} />;
            if (item.type === "label")
              return (
                <DropdownMenu.Label key={item.key} className={styles.menuLabel}>
                  {item.label}
                </DropdownMenu.Label>
              );
            return (
              <DropdownMenu.Item
                key={item.key}
                className={`${styles.menuItem} ${item.danger ? styles.menuItemDanger : ""}`}
                disabled={item.disabled}
                onSelect={item.onSelect}
              >
                {item.icon}
                <span>{item.label}</span>
              </DropdownMenu.Item>
            );
          })}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
