import { cn } from "@/lib/utils";

interface LogoProps {
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  className?: string;
  collapsed?: boolean;
}

const sizeClasses = {
  xs: "text-sm",
  sm: "text-2xl",
  md: "text-2xl",
  lg: "text-3xl",
  xl: "text-5xl md:text-6xl",
};

export function Logo({
  size = "md",
  className = "",
  collapsed = false,
}: LogoProps) {
  const sizeClass = sizeClasses[size];

  if (collapsed) {
    return (
      <span
        className={cn(
          "font-semibold italic tracking-tight",
          sizeClass,
          className,
        )}
      >
        <span className="text-accent">q</span>
        <span className="text-foreground">c</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        "font-semibold italic tracking-tight",
        sizeClass,
        className,
      )}
    >
      <span className="text-accent">quick</span>
      <span className="text-foreground">call</span>
    </span>
  );
}
