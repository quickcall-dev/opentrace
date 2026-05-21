"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import {
  Dropdown,
  DropdownTrigger,
  DropdownContent,
  useDropdown,
} from "@/components/ui/dropdown";

const DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function intensity(count: number, max: number): number {
  if (count === 0) return 0;
  if (max <= 1) return 4;
  const ratio = count / max;
  if (ratio >= 0.75) return 4;
  if (ratio >= 0.4) return 3;
  if (ratio >= 0.15) return 2;
  return 1;
}

const INTENSITY_BG = ["", "bg-accent/30", "bg-accent/50", "bg-accent/70", "bg-accent"];
const INTENSITY_TEXT = ["", "text-accent-foreground", "text-accent-foreground", "text-white", "text-white"];

interface CalendarPickerProps {
  value: string | undefined;
  onChange: (date: string | undefined) => void;
  activeDates?: Map<string, number>;
}

export function CalendarPicker({ value, onChange, activeDates }: CalendarPickerProps) {
  const buttonLabel = value
    ? new Date(value + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : "All dates";

  return (
    <Dropdown>
      <DropdownTrigger variant={value ? "active" : "default"}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0">
          <rect x="3" y="4" width="18" height="18" rx="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
        <span>{buttonLabel}</span>
      </DropdownTrigger>
      <DropdownContent align="right" portal className="w-[250px] p-2.5 overflow-visible">
        <CalendarGrid value={value} onChange={onChange} activeDates={activeDates} />
      </DropdownContent>
    </Dropdown>
  );
}

function CalendarGrid({
  value,
  onChange,
  activeDates,
}: CalendarPickerProps) {
  const { close } = useDropdown();

  const [viewYear, setViewYear] = useState(() => {
    if (value) return parseInt(value.slice(0, 4));
    return new Date().getFullYear();
  });
  const [viewMonth, setViewMonth] = useState(() => {
    if (value) return parseInt(value.slice(5, 7)) - 1;
    return new Date().getMonth();
  });

  useEffect(() => {
    if (value) {
      setViewYear(parseInt(value.slice(0, 4)));
      setViewMonth(parseInt(value.slice(5, 7)) - 1);
    }
  }, [value]);

  const maxInMonth = useMemo(() => {
    if (!activeDates) return 0;
    const prefix = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}`;
    let max = 0;
    activeDates.forEach((count, date) => {
      if (date.startsWith(prefix) && count > max) max = count;
    });
    return max;
  }, [activeDates, viewYear, viewMonth]);

  const handleMonthNav = useCallback((dir: -1 | 1) => {
    let newMonth = viewMonth + dir;
    let newYear = viewYear;
    if (newMonth < 0) { newMonth = 11; newYear--; }
    if (newMonth > 11) { newMonth = 0; newYear++; }
    setViewMonth(newMonth);
    setViewYear(newYear);
  }, [viewMonth, viewYear]);

  const selectDate = useCallback((dateStr: string) => {
    onChange(dateStr);
    close();
  }, [onChange, close]);

  const clearDate = useCallback(() => {
    onChange(undefined);
    close();
  }, [onChange, close]);

  const grid = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1).getDay();
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const daysInPrev = new Date(viewYear, viewMonth, 0).getDate();
    const today = new Date().toISOString().slice(0, 10);

    type Cell = { day: number; dateStr: string; outside: boolean; count: number; isSelected: boolean; isToday: boolean };
    const cells: Cell[] = [];

    for (let i = firstDay - 1; i >= 0; i--) {
      const d = daysInPrev - i;
      const m = viewMonth === 0 ? 12 : viewMonth;
      const y = viewMonth === 0 ? viewYear - 1 : viewYear;
      const ds = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      cells.push({ day: d, dateStr: ds, outside: true, count: activeDates?.get(ds) ?? 0, isSelected: value === ds, isToday: ds === today });
    }

    for (let d = 1; d <= daysInMonth; d++) {
      const ds = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      cells.push({ day: d, dateStr: ds, outside: false, count: activeDates?.get(ds) ?? 0, isSelected: value === ds, isToday: ds === today });
    }

    const remaining = 7 - (cells.length % 7);
    if (remaining < 7) {
      for (let d = 1; d <= remaining; d++) {
        const m = viewMonth === 11 ? 1 : viewMonth + 2;
        const y = viewMonth === 11 ? viewYear + 1 : viewYear;
        const ds = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
        cells.push({ day: d, dateStr: ds, outside: true, count: activeDates?.get(ds) ?? 0, isSelected: value === ds, isToday: ds === today });
      }
    }

    return cells;
  }, [viewYear, viewMonth, value, activeDates]);

  const activeDatesInMonth = useMemo(() => {
    if (!activeDates) return 0;
    const prefix = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}`;
    let count = 0;
    activeDates.forEach((_, date) => { if (date.startsWith(prefix)) count++; });
    return count;
  }, [activeDates, viewYear, viewMonth]);

  const totalInMonth = useMemo(() => {
    if (!activeDates) return 0;
    const prefix = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}`;
    let total = 0;
    activeDates.forEach((c, date) => { if (date.startsWith(prefix)) total += c; });
    return total;
  }, [activeDates, viewYear, viewMonth]);

  const monthLabel = new Date(viewYear, viewMonth).toLocaleDateString("en-US", { month: "short", year: "numeric" });

  return (
    <>
      {/* Month nav */}
      <div className="flex items-center justify-between mb-2">
        <button
          onClick={() => handleMonthNav(-1)}
          className="w-6 h-6 flex items-center justify-center rounded hover:bg-muted text-muted-foreground text-sm font-medium"
        >
          ‹
        </button>
        <div className="text-center">
          <span className="text-[11px] font-semibold text-foreground">{monthLabel}</span>
          {totalInMonth > 0 && (
            <div className="text-[0.6875rem] text-muted-foreground">{totalInMonth} sessions · {activeDatesInMonth} days</div>
          )}
        </div>
        <button
          onClick={() => handleMonthNav(1)}
          className="w-6 h-6 flex items-center justify-center rounded hover:bg-muted text-muted-foreground text-sm font-medium"
        >
          ›
        </button>
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 gap-0.5 mb-0.5">
        {DAYS.map((d) => (
          <div key={d} className="text-center text-[0.6875rem] text-muted-foreground font-medium py-0.5">{d}</div>
        ))}
      </div>

      {/* Day grid */}
      <div className="grid grid-cols-7 gap-0.5">
        {grid.map((cell, i) => {
          const level = cell.count > 0 ? intensity(cell.count, maxInMonth) : 0;
          return (
            <button
              key={i}
              onClick={() => selectDate(cell.dateStr)}
              title={cell.count > 0 ? `${cell.dateStr}: ${cell.count} sessions` : cell.dateStr}
              data-testid={cell.count > 0 && !cell.outside ? "calendar-active-date" : undefined}
              className={cn(
                "relative w-full aspect-square flex items-center justify-center text-[0.6875rem] rounded-sm transition-all",
                cell.outside && "opacity-30",
                !cell.outside && level === 0 && "bg-muted text-muted-foreground hover:bg-muted",
                !cell.outside && level > 0 && INTENSITY_BG[level],
                !cell.outside && level > 0 && INTENSITY_TEXT[level],
                !cell.outside && level > 0 && "font-semibold",
                cell.isSelected && "after:absolute after:bottom-0.5 after:left-1/2 after:-translate-x-1/2 after:w-1 after:h-1 after:rounded-full after:bg-foreground",
                cell.isToday && !cell.isSelected && level === 0 && "ring-1 ring-accent ring-inset",
              )}
            >
              {cell.day}
            </button>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-border">
        <button onClick={clearDate} className="text-[0.6875rem] text-muted-foreground hover:text-foreground">
          All dates
        </button>
        {activeDates ? (
          <div className="flex items-center gap-0.5">
            <span className="text-[0.6875rem] text-muted-foreground mr-1">Less</span>
            <span className="w-2.5 h-2.5 rounded-sm bg-muted border border-border" />
            <span className="w-2.5 h-2.5 rounded-sm bg-accent/30" />
            <span className="w-2.5 h-2.5 rounded-sm bg-accent/50" />
            <span className="w-2.5 h-2.5 rounded-sm bg-accent/70" />
            <span className="w-2.5 h-2.5 rounded-sm bg-accent" />
            <span className="text-[0.6875rem] text-muted-foreground ml-1">More</span>
          </div>
        ) : (
          <div />
        )}
        <button
          onClick={() => selectDate(new Date().toISOString().slice(0, 10))}
          className="text-[0.6875rem] text-foreground underline decoration-muted-foreground/40 hover:decoration-foreground font-medium"
        >
          Today
        </button>
      </div>
    </>
  );
}
