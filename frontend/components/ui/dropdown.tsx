"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

/* ── Context ── */

interface DropdownCtx {
  open: boolean;
  setOpen: (v: boolean) => void;
  toggle: () => void;
  close: () => void;
  rootRef: React.RefObject<HTMLDivElement | null>;
  portalRef: React.RefObject<HTMLDivElement | null>;
}

const Ctx = createContext<DropdownCtx | null>(null);

function useDropdown() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useDropdown must be used within <Dropdown>");
  return ctx;
}

/* ── Root ── */

interface DropdownProps {
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}

function Dropdown({ children, open: controlledOpen, onOpenChange, className }: DropdownProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;

  const setOpen = useCallback(
    (v: boolean) => {
      if (!isControlled) setInternalOpen(v);
      onOpenChange?.(v);
    },
    [isControlled, onOpenChange],
  );

  const toggle = useCallback(() => setOpen(!open), [open, setOpen]);
  const close = useCallback(() => setOpen(false), [setOpen]);

  const ref = useRef<HTMLDivElement>(null);
  const portalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current && !ref.current.contains(target) && !portalRef.current?.contains(target)) close();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, close]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, close]);

  return (
    <Ctx.Provider value={{ open, setOpen, toggle, close, rootRef: ref, portalRef }}>
      <div ref={ref} className={cn("relative", className)}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

/* ── Trigger ── */

type TriggerVariant = "default" | "active" | "ghost";

interface DropdownTriggerProps {
  children: ReactNode;
  variant?: TriggerVariant;
  className?: string;
}

const triggerStyles: Record<TriggerVariant, string> = {
  default:
    "bg-card border border-border text-muted-foreground hover:bg-muted",
  active:
    "bg-teal-50 dark:bg-teal-950/30 border border-teal-400 dark:border-teal-600 text-teal-700 dark:text-teal-300",
  ghost:
    "text-muted-foreground hover:bg-muted",
};

function DropdownTrigger({ children, variant = "default", className }: DropdownTriggerProps) {
  const { toggle, open } = useDropdown();

  return (
    <button
      onClick={toggle}
      aria-expanded={open}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/40",
        triggerStyles[variant],
        className,
      )}
    >
      {children}
      <svg
        width="10"
        height="10"
        viewBox="0 0 10 10"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className={cn("shrink-0 transition-transform", open && "rotate-180")}
      >
        <path d="M2.5 4L5 6.5L7.5 4" />
      </svg>
    </button>
  );
}

/* ── Content (panel) ── */

type Align = "left" | "right";

interface DropdownContentProps {
  children: ReactNode;
  align?: Align;
  direction?: "down" | "up";
  /** Render via portal at body level — escapes overflow:hidden and stacking contexts */
  portal?: boolean;
  className?: string;
}

function DropdownContent({ children, align = "left", direction = "down", portal = false, className }: DropdownContentProps) {
  const { open, rootRef, portalRef } = useDropdown();
  const contentRef = useRef<HTMLDivElement>(null);

  // Sync portal ref so outside-click detection works
  useEffect(() => {
    if (portal && contentRef.current) {
      (portalRef as React.MutableRefObject<HTMLDivElement | null>).current = contentRef.current;
    }
    return () => {
      if (portal) {
        (portalRef as React.MutableRefObject<HTMLDivElement | null>).current = null;
      }
    };
  });
  const [resolvedDir, setResolvedDir] = useState<"up" | "down">(direction);
  const [portalStyle, setPortalStyle] = useState<React.CSSProperties>({});

  useLayoutEffect(() => {
    if (!open) {
      setResolvedDir(direction);
      return;
    }

    const root = rootRef.current;
    const content = contentRef.current;
    if (!root || !content) {
      setResolvedDir(direction);
      return;
    }

    const rootRect = root.getBoundingClientRect();
    const contentHeight = content.scrollHeight;
    const contentWidth = content.offsetWidth;
    const spaceBelow = window.innerHeight - rootRect.bottom;
    const spaceAbove = rootRect.top;

    let dir: "up" | "down";
    if (direction === "down") {
      dir = (contentHeight > spaceBelow && spaceAbove > spaceBelow) ? "up" : "down";
    } else {
      dir = (contentHeight > spaceAbove && spaceBelow > spaceAbove) ? "down" : "up";
    }
    setResolvedDir(dir);

    if (portal) {
      const style: React.CSSProperties = {
        position: "fixed",
        zIndex: 9999,
      };
      if (dir === "down") {
        style.top = rootRect.bottom + 4;
      } else {
        style.bottom = window.innerHeight - rootRect.top + 4;
      }
      if (align === "right") {
        style.right = window.innerWidth - rootRect.right;
      } else {
        style.left = rootRect.left;
      }
      // Clamp to viewport
      if (align === "left" && (rootRect.left + contentWidth) > window.innerWidth) {
        style.left = window.innerWidth - contentWidth - 8;
      }
      setPortalStyle(style);
    }
  }, [open, direction, portal, align, rootRef]);

  if (!open) return null;

  const panel = (
    <div
      ref={contentRef}
      style={portal ? portalStyle : undefined}
      className={cn(
        portal ? "" : "absolute z-50",
        !portal && (resolvedDir === "up" ? "bottom-full mb-1" : "top-full mt-1"),
        "bg-card border border-border rounded-xl shadow-lg",
        "min-w-[180px] max-h-[320px] overflow-auto",
        "animate-in fade-in-0 zoom-in-95 duration-100",
        !portal && (align === "right" ? "right-0" : "left-0"),
        className,
      )}
    >
      {children}
    </div>
  );

  if (portal) {
    return createPortal(panel, document.body);
  }

  return panel;
}

/* ── Convenience sub-components ── */

function DropdownLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "px-3 py-1.5 text-[0.6875rem] font-semibold text-muted-foreground uppercase tracking-wider",
        className,
      )}
    >
      {children}
    </div>
  );
}

interface DropdownItemProps {
  children: ReactNode;
  onClick?: () => void;
  className?: string;
}

function DropdownItem({ children, onClick, className }: DropdownItemProps) {
  const { close } = useDropdown();

  return (
    <button
      onClick={() => {
        onClick?.();
        close();
      }}
      className={cn(
        "w-full text-left px-3 py-1.5 text-xs text-foreground",
        "hover:bg-muted transition-colors",
        "flex items-center gap-2",
        className,
      )}
    >
      {children}
    </button>
  );
}

function DropdownSeparator({ className }: { className?: string }) {
  return <div className={cn("border-t border-border my-0.5", className)} />;
}

export {
  Dropdown,
  DropdownTrigger,
  DropdownContent,
  DropdownLabel,
  DropdownItem,
  DropdownSeparator,
  useDropdown,
};
